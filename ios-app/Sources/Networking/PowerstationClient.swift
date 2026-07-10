//
//  PowerstationClient.swift
//  Powerstation
//
//  Native TCP client for the power station's local control socket,
//  default 192.168.4.1:5000. Direct port of PowerstationClient in
//  powerstation_control.py, using Network.framework instead of sockets.
//
//  Connection sequence: device sends an unsolicited '61' identification
//  frame on connect; we ack it, then send '24'/'01' to enter control
//  mode. Once acked, the device pushes status ('93') roughly every 3s
//  for the life of the connection.
//

import Foundation
import Network

enum PowerstationError: LocalizedError {
    case notConnected
    case connectionFailed(String)
    case timeout(String)
    case invalidArgument(String)
    case protocolError(String)

    var errorDescription: String? {
        switch self {
        case .notConnected: return "Not connected to the power station."
        case .connectionFailed(let m): return "Connection failed: \(m)"
        case .timeout(let m): return m
        case .invalidArgument(let m): return m
        case .protocolError(let m): return m
        }
    }
}

struct PowerstationFrame {
    let command: String
    let data: String
}

/// All mutable state is confined to `queue`; public methods are async
/// and hop onto that queue via continuations. Marked unchecked-Sendable
/// on that basis.
final class PowerstationClient: @unchecked Sendable {

    static let defaultHost = "192.168.4.1"
    static let defaultPort: UInt16 = 5000

    let host: String
    let port: UInt16

    private let queue = DispatchQueue(label: "com.powerstation.client")
    private var connection: NWConnection?
    private var recvBuffer = Data()
    private var serial = "0001"
    private var handshakeDone = false
    private var cachedStatusHex: (String, Date)?
    private var isConnectedInternal = false

    private final class Waiter {
        let expected: Set<String>
        let continuation: CheckedContinuation<PowerstationFrame, Error>
        var timeoutWorkItem: DispatchWorkItem?
        init(expected: Set<String>, continuation: CheckedContinuation<PowerstationFrame, Error>) {
            self.expected = expected
            self.continuation = continuation
        }
    }
    private var waiters: [Waiter] = []

    /// Called (off the main thread) whenever a fresh '93' status push arrives.
    var onStatusUpdate: ((PowerstationStatus) -> Void)?

    /// Serializes the compound "read current shared byte, flip one bit,
    /// write the whole byte back" commands (switch bitmask, AmpUp/Sleep/
    /// ChargeSpeed byte). Without this, two overlapping calls — e.g.
    /// tapping AC then DC in quick succession — can each read the same
    /// stale snapshot and then write it back with only their own bit
    /// changed, silently reverting whichever call's write lands first,
    /// since each command replaces the entire shared register at once.
    private let commandGate = AsyncGate()

    private func withCommandLock<T>(_ operation: () async throws -> T) async throws -> T {
        await commandGate.acquire()
        do {
            let result = try await operation()
            await commandGate.release()
            return result
        } catch {
            await commandGate.release()
            throw error
        }
    }

    init(host: String = PowerstationClient.defaultHost, port: UInt16 = PowerstationClient.defaultPort) {
        self.host = host
        self.port = port
    }

    var isConnected: Bool {
        get async { await onQueue { self.isConnectedInternal } }
    }

    // MARK: - Connection

    func connect(timeout: TimeInterval = 5.0) async throws {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<Void, Error>) in
            queue.async {
                let params = NWParameters.tcp
                let conn = NWConnection(host: NWEndpoint.Host(self.host),
                                        port: NWEndpoint.Port(integerLiteral: self.port),
                                        using: params)
                self.connection = conn
                self.recvBuffer = Data()
                self.serial = "0001"
                self.handshakeDone = false

                var didResume = false
                let timeoutItem = DispatchWorkItem {
                    if !didResume {
                        didResume = true
                        conn.cancel()
                        cont.resume(throwing: PowerstationError.connectionFailed("timed out after \(Int(timeout))s"))
                    }
                }
                self.queue.asyncAfter(deadline: .now() + timeout, execute: timeoutItem)

                conn.stateUpdateHandler = { [weak self] state in
                    guard let self = self else { return }
                    switch state {
                    case .ready:
                        if !didResume {
                            didResume = true
                            timeoutItem.cancel()
                            self.isConnectedInternal = true
                            self.startReceiveLoop()
                            cont.resume()
                        }
                    case .failed(let err):
                        if !didResume {
                            didResume = true
                            timeoutItem.cancel()
                            cont.resume(throwing: PowerstationError.connectionFailed(err.localizedDescription))
                        }
                        self.isConnectedInternal = false
                    case .cancelled:
                        self.isConnectedInternal = false
                    default:
                        break
                    }
                }
                conn.start(queue: self.queue)
            }
        }
    }

    func disconnect() {
        queue.async {
            self.connection?.cancel()
            self.connection = nil
            self.isConnectedInternal = false
            self.handshakeDone = false
            self.cachedStatusHex = nil
            self.recvBuffer = Data()
            self.failAllWaiters(PowerstationError.connectionFailed("disconnected"))
        }
    }

    private func failAllWaiters(_ error: Error) {
        let all = waiters
        waiters.removeAll()
        for w in all {
            w.timeoutWorkItem?.cancel()
            w.continuation.resume(throwing: error)
        }
    }

    // MARK: - Receive loop

    private func startReceiveLoop() {
        connection?.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self = self else { return }
            self.queue.async {
                if let data = data, !data.isEmpty {
                    self.recvBuffer.append(data)
                    self.drainBuffer()
                }
                if let error = error {
                    self.isConnectedInternal = false
                    self.failAllWaiters(PowerstationError.connectionFailed(error.localizedDescription))
                    return
                }
                if isComplete {
                    self.isConnectedInternal = false
                    self.failAllWaiters(PowerstationError.connectionFailed("connection closed by device"))
                    return
                }
                self.startReceiveLoop()
            }
        }
    }

    private func lossyASCII(_ data: Data) -> String {
        String(data: data.filter { $0 < 0x80 }, encoding: .ascii) ?? ""
    }

    /// Resync to frame boundaries and process every complete AA55...CC33
    /// frame currently buffered. Must run on `queue`.
    private func drainBuffer() {
        while true {
            guard let startRange = recvBuffer.range(of: Data("AA55".utf8)) else {
                recvBuffer.removeAll()
                return
            }
            if startRange.lowerBound > recvBuffer.startIndex {
                recvBuffer.removeSubrange(recvBuffer.startIndex..<startRange.lowerBound)
            }
            guard let endRange = recvBuffer.range(of: Data("CC33".utf8)) else {
                return // wait for more data
            }
            let frameEnd = endRange.upperBound
            let rawFrameData = recvBuffer.subdata(in: recvBuffer.startIndex..<frameEnd)
            recvBuffer.removeSubrange(recvBuffer.startIndex..<frameEnd)
            handleFrameText(lossyASCII(rawFrameData))
        }
    }

    /// Must run on `queue`.
    private func handleFrameText(_ text: String) {
        guard PowerstationProtocol.frameCRCOK(text) else { return }
        guard let (cmd, data) = PowerstationProtocol.parseResponseFrame(text) else { return }

        if text.count >= 12 {
            let idx0 = text.index(text.startIndex, offsetBy: 8)
            let idx1 = text.index(text.startIndex, offsetBy: 12)
            serial = PowerstationProtocol.autoIncrementSerial(String(text[idx0..<idx1]))
        }

        if cmd == "61" {
            sendFrame(command: "61", data: "55")
            // Ask for control mode every time we see '61' — on the very
            // first connection (handshakeDone starts false) as much as
            // on a mid-session reset where the device re-announces
            // itself. Previously this was only sent when handshakeDone
            // was already true, which meant the very first connection
            // never actually requested control and just sat waiting for
            // a '24' reply that was never coming.
            handshakeDone = false
            sendFrame(command: "24", data: "01")
        } else if cmd == "24" {
            // Any '24' ack is treated as "ready for control" — matches
            // quick_connect()'s behavior in the Python client.
            handshakeDone = true
        }

        if cmd == "93" {
            cachedStatusHex = (data, Date())
            if let status = PowerstationStatus(hexPayload: data) {
                let callback = onStatusUpdate
                DispatchQueue.main.async { callback?(status) }
            }
        }

        for i in waiters.indices.reversed() where waiters[i].expected.contains(cmd) {
            let w = waiters.remove(at: i)
            w.timeoutWorkItem?.cancel()
            w.continuation.resume(returning: PowerstationFrame(command: cmd, data: data))
        }
    }

    private func sendFrame(command: String, data: String, encoding: PowerstationProtocol.Encoding = .base2) {
        let msg = PowerstationProtocol.buildFrame(serial: serial, command: command, data: data, encoding: encoding)
        serial = PowerstationProtocol.autoIncrementSerial(serial)
        connection?.send(content: msg.data(using: .ascii), completion: .contentProcessed { _ in })
    }

    // MARK: - Waiting helpers

    private func onQueue<T>(_ body: @escaping () -> T) async -> T {
        await withCheckedContinuation { cont in
            queue.async { cont.resume(returning: body()) }
        }
    }

    /// Registers a waiter for any frame whose command is in `expected`,
    /// optionally performing `sendAction` right after registering (so a
    /// fast reply can never race ahead of the waiter).
    private func _waitForFrame(expected: Set<String>, timeout: TimeInterval,
                                thenSend sendAction: (() -> Void)? = nil) async throws -> PowerstationFrame {
        try await withCheckedThrowingContinuation { (cont: CheckedContinuation<PowerstationFrame, Error>) in
            queue.async {
                let waiter = Waiter(expected: expected, continuation: cont)
                self.waiters.append(waiter)
                let workItem = DispatchWorkItem { [weak self, weak waiter] in
                    guard let self = self, let waiter = waiter else { return }
                    self.queue.async {
                        if let idx = self.waiters.firstIndex(where: { $0 === waiter }) {
                            self.waiters.remove(at: idx)
                            waiter.continuation.resume(throwing: PowerstationError.timeout("Timed out waiting for \(expected)"))
                        }
                    }
                }
                waiter.timeoutWorkItem = workItem
                sendAction?()
                self.queue.asyncAfter(deadline: .now() + timeout, execute: workItem)
            }
        }
    }

    /// Runs the '61'/'24' handshake if not already done on this connection.
    func quickConnect(timeout: TimeInterval = 15.0) async throws {
        if await onQueue({ self.handshakeDone }) { return }
        _ = try await _waitForFrame(expected: ["24"], timeout: timeout)
    }

    /// Send a command and wait for a matching response.
    @discardableResult
    func sendCommand(_ command: String, data: String, encoding: PowerstationProtocol.Encoding = .base2,
                      timeout: TimeInterval, expected: Set<String>? = nil) async throws -> PowerstationFrame {
        guard await isConnected else { throw PowerstationError.notConnected }
        if command != "61", command != "24", !(await onQueue({ self.handshakeDone })) {
            try await quickConnect(timeout: 15.0)
        }
        let expectedCmds = expected ?? [command]
        return try await _waitForFrame(expected: expectedCmds, timeout: timeout) {
            self.sendFrame(command: command, data: data, encoding: encoding)
        }
    }

    /// Send a command without waiting for any response.
    func sendFireAndForget(_ command: String, data: String, encoding: PowerstationProtocol.Encoding = .base2) async throws {
        guard await isConnected else { throw PowerstationError.notConnected }
        if command != "61", command != "24", !(await onQueue({ self.handshakeDone })) {
            try await quickConnect(timeout: 15.0)
        }
        await onQueue { self.sendFrame(command: command, data: data, encoding: encoding) }
    }

    // MARK: - Status

    /// One-shot status request (command '34'). Prefer waitForStatusPush()
    /// for normal polling — '34' itself triggers nothing; the device
    /// pushes '93' on its own schedule regardless.
    func requestStatus() async throws -> PowerstationStatus {
        let frame = try await sendCommand("34", data: "01", timeout: 5.0, expected: ["34", "79", "75", "93"])
        guard let status = PowerstationStatus(hexPayload: frame.data) else {
            throw PowerstationError.protocolError("Unrecognized status response")
        }
        return status
    }

    /// Waits for the device's next unsolicited '93' status push (sent
    /// roughly every 3s once connected). Uses a recently-cached push
    /// (e.g. one that arrived mid-handshake) if it's still fresh.
    func waitForStatusPush(timeout: TimeInterval = 8.0, maxCacheAge: TimeInterval = 4.0) async throws -> PowerstationStatus {
        if !(await onQueue({ self.handshakeDone })) {
            try await quickConnect(timeout: 15.0)
        }
        let cached: (String, Date)? = await onQueue {
            let c = self.cachedStatusHex
            self.cachedStatusHex = nil
            return c
        }
        if let (hex, ts) = cached, Date().timeIntervalSince(ts) <= maxCacheAge,
           let status = PowerstationStatus(hexPayload: hex) {
            return status
        }
        let frame = try await _waitForFrame(expected: ["93"], timeout: timeout)
        guard let status = PowerstationStatus(hexPayload: frame.data) else {
            throw PowerstationError.protocolError("Could not parse status payload")
        }
        return status
    }

    // MARK: - Switch controls (bitmask command '12')
    // master/AC/DC/ambient-light/buzzer route through the shared 8-bit
    // bitmask, not the documented single-purpose commands, which are
    // gated behind a firmware flag this device doesn't set.

    private static let legacyBitmaskPositions =
        ["ac_hz", "unknown_bit1", "unknown_bit2", "ambient_light", "buzzer", "dc", "ac", "master"]

    private func toggleLegacyBitmask(_ name: String, on: Bool) async throws {
        guard Self.legacyBitmaskPositions.contains(name) else {
            throw PowerstationError.invalidArgument("Unknown switch \(name)")
        }
        try await withCommandLock {
            let status = try await waitForStatusPush(timeout: 8.0)
            guard let switches = status.switches else {
                throw PowerstationError.protocolError("Could not read current switch state before toggling.")
            }
            var bits = ""
            for pos in Self.legacyBitmaskPositions {
                bits += (pos == name ? on : (switches[pos] ?? false)) ? "1" : "0"
            }
            guard let value = UInt8(bits, radix: 2) else {
                throw PowerstationError.protocolError("Failed to build bitmask")
            }
            _ = try await sendCommand("12", data: String(format: "%02X", value), timeout: 3.0, expected: ["12"])
        }
    }

    func setMasterSwitch(_ on: Bool) async throws { try await toggleLegacyBitmask("master", on: on) }
    func setACOutput(_ on: Bool) async throws { try await toggleLegacyBitmask("ac", on: on) }
    func setDCOutput(_ on: Bool) async throws { try await toggleLegacyBitmask("dc", on: on) }
    func setAmbientLight(_ on: Bool) async throws { try await toggleLegacyBitmask("ambient_light", on: on) }
    func setBuzzer(_ on: Bool) async throws { try await toggleLegacyBitmask("buzzer", on: on) }

    func setFourGSwitch(_ on: Bool) async throws {
        // Command '58': no supporting evidence in source of doing anything
        // locally — see README. Included for completeness only.
        try await sendFireAndForget("58", data: on ? "00" : "01")
    }

    // Command '62' (AC output frequency) was removed: testing showed it
    // has no observable effect on this device.

    // MARK: - Shared AmpUp/Sleep/ChargeSpeed byte (command '20')

    func setAmpUpMode(_ on: Bool) async throws {
        try await withCommandLock {
            let status = try await waitForStatusPush(timeout: 8.0)
            let current = status.ampByteRaw ?? 0
            let newByte = on ? (current | 0x01) : (current & 0xFE)
            _ = try await sendCommand("20", data: String(format: "%02X", UInt8(newByte & 0xFF)), timeout: 2.0)
        }
    }

    func setSleepMode(_ on: Bool) async throws {
        try await withCommandLock {
            let status = try await waitForStatusPush(timeout: 8.0)
            let current = status.ampByteRaw ?? 0
            let newByte = on ? (current | 0x02) : (current & 0xFD)
            _ = try await sendCommand("20", data: String(format: "%02X", UInt8(newByte & 0xFF)), timeout: 2.0)
        }
    }

    func setMaxChargeWatts(_ watts: Int) async throws {
        let levelMap: [Int: Int] = [300: 1, 500: 2, 800: 3, 1200: 4, 1800: 5]
        guard let level = levelMap[watts] else {
            throw PowerstationError.invalidArgument("Max charge watts must be one of 300, 500, 800, 1200, 1800")
        }
        try await withCommandLock {
            let status = try await waitForStatusPush(timeout: 8.0)
            if status.sleepMode == true {
                throw PowerstationError.protocolError("Can't change charge speed while sleep mode is on. Turn off sleep mode first.")
            }
            let current = status.ampByteRaw ?? 0
            let newByte = (current & 0x1F) | (level << 5)
            _ = try await sendCommand("20", data: String(format: "%02X", UInt8(newByte & 0xFF)), timeout: 2.0)
        }
    }

    // MARK: - Charge limit (command '18')

    func setChargeLimit(_ percent: Int) async throws {
        let levelMap: [Int: Int] = [100: 1, 90: 2, 80: 3, 70: 4]
        guard let level = levelMap[percent] else {
            throw PowerstationError.invalidArgument("Charge limit must be one of 100, 90, 80, 70")
        }
        let combined = PowerstationProtocol.binaryPadded(level, width: 4) + "0001"
        guard let value = UInt8(combined, radix: 2) else {
            throw PowerstationError.protocolError("Failed to encode charge limit")
        }
        try await sendFireAndForget("18", data: String(format: "%02X", value))
    }

    // MARK: - Standby levels (command '16')

    func setStandbyLevels(machineLevel: Int, screenLevel: Int) async throws {
        guard (1...6).contains(machineLevel) else {
            throw PowerstationError.invalidArgument("machine level must be 1-6 (6 = never)")
        }
        guard (1...6).contains(screenLevel) else {
            throw PowerstationError.invalidArgument("screen level must be 1-6 (6 = never)")
        }
        let fullBin = "0" + PowerstationProtocol.binaryPadded(machineLevel, width: 3)
                          + PowerstationProtocol.binaryPadded(screenLevel, width: 3) + "0"
        guard let value = UInt8(fullBin, radix: 2) else {
            throw PowerstationError.protocolError("Failed to encode standby levels")
        }
        try await sendFireAndForget("16", data: String(format: "%02X", value))
    }

    func setKeepPoweredOn(_ enabled: Bool, screenLevel: Int, offLevel: Int = 1) async throws {
        try await setStandbyLevels(machineLevel: enabled ? 6 : offLevel, screenLevel: screenLevel)
    }

    // MARK: - LED (command '22')

    func setLEDColorAndBrightness(colorId: Int, brightness: Int) async throws {
        guard (1...10).contains(colorId) else {
            throw PowerstationError.invalidArgument("Color ID must be between 1 and 10")
        }
        guard (0...100).contains(brightness) else {
            throw PowerstationError.invalidArgument("Brightness must be between 0 and 100")
        }
        // Mode type must be '111' (static/manual) — '001' puts the LED in
        // the wrong mode and produces a bogus reported brightness.
        let fullBin = "111" + PowerstationProtocol.binaryPadded(colorId, width: 5)
                            + PowerstationProtocol.binaryPadded(brightness, width: 8)
        guard let value = UInt16(fullBin, radix: 2) else {
            throw PowerstationError.protocolError("Failed to encode LED command")
        }
        var hexStr = String(value, radix: 16).uppercased()
        if hexStr.count % 2 == 1 { hexStr = "0" + hexStr }
        try await sendFireAndForget("22", data: hexStr)
    }

    func setLEDBrightness(_ brightness: Int) async throws {
        let status = try await waitForStatusPush(timeout: 8.0)
        let currentColor = status.ambientColor.flatMap { $0 == 0 ? nil : $0 } ?? 1
        try await setLEDColorAndBrightness(colorId: currentColor, brightness: brightness)
    }

    func setLEDColor(_ colorId: Int) async throws {
        let status = try await waitForStatusPush(timeout: 8.0)
        let currentBrightness = status.ambientLightness ?? 0
        try await setLEDColorAndBrightness(colorId: colorId, brightness: currentBrightness)
    }

    // MARK: - Undocumented / experimental commands (found by probing)

    /// Turns AmpUp mode on directly via command '20', data '01'.
    func triggerAmpUpOn() async throws {
        _ = try await sendCommand("20", data: "01", timeout: 2.0)
    }
}

/// A minimal FIFO async mutex. Being an `actor`, its own state (`isLocked`,
/// `waiters`) is race-free by construction — no manually-managed locks or
/// captured mutable state across closures, which is what makes this safe
/// under Swift's strict concurrency checking.
private actor AsyncGate {
    private var isLocked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func acquire() async {
        if !isLocked {
            isLocked = true
            return
        }
        await withCheckedContinuation { waiters.append($0) }
    }

    func release() {
        if waiters.isEmpty {
            isLocked = false
        } else {
            waiters.removeFirst().resume()
        }
    }
}
