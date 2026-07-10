//
//  PowerstationViewModel.swift
//  Powerstation
//

import Foundation
import SwiftUI
import Combine

// Deliberately NOT marked @MainActor at the class level — under Swift's
// strict (Swift 6) concurrency checking, a MainActor-isolated class can
// fail ObservableObject's conformance synthesis (objectWillChange is a
// nonisolated protocol requirement), and that failure surfaces
// confusingly at wherever the type is *used* (e.g. @EnvironmentObject
// in ContentView) rather than here. Isolating each Task body to
// @MainActor individually gets the same thread-safety guarantee for
// @Published writes without that risk.
final class PowerstationViewModel: ObservableObject {

    @Published var host: String
    @Published var port: String
    @Published var isConnected = false
    @Published var isConnecting = false
    @Published var status: PowerstationStatus?
    @Published var lastError: String?
    @Published private var activeCommandCount = 0

    /// True while any setting change is in flight — drives the
    /// "Applying Setting…" toast. A counter rather than a plain bool
    /// so overlapping commands (e.g. a quick double-tap) don't cause
    /// one finishing early to hide the toast while another is still
    /// pending.
    var isApplyingSetting: Bool { activeCommandCount > 0 }

    private var client: PowerstationClient?
    private var pollTask: Task<Void, Never>?

    init() {
        let defaults = UserDefaults.standard
        host = defaults.string(forKey: "ps.host") ?? PowerstationClient.defaultHost
        port = defaults.string(forKey: "ps.port") ?? String(PowerstationClient.defaultPort)
    }

    func saveConnectionSettings() {
        UserDefaults.standard.set(host, forKey: "ps.host")
        UserDefaults.standard.set(port, forKey: "ps.port")
    }

    func connect() {
        saveConnectionSettings()
        guard let portNum = UInt16(port) else {
            lastError = "Invalid port number"
            return
        }
        isConnecting = true
        lastError = nil
        let newClient = PowerstationClient(host: host, port: portNum)
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await newClient.connect(timeout: 5.0)
                self.client = newClient
                self.isConnected = true
                self.isConnecting = false
                self.startPolling()
            } catch {
                self.isConnecting = false
                self.isConnected = false
                self.lastError = error.localizedDescription
            }
        }
    }

    func disconnect() {
        pollTask?.cancel()
        pollTask = nil
        client?.disconnect()
        client = nil
        isConnected = false
        status = nil
    }

    private func startPolling() {
        pollTask?.cancel()
        pollTask = Task { @MainActor [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                guard let client = self.client else { break }
                do {
                    let s = try await client.waitForStatusPush(timeout: 8.0)
                    self.status = s
                    self.lastError = nil
                } catch {
                    self.lastError = error.localizedDescription
                    self.isConnected = false
                    break
                }
            }
        }
    }

    private func run(_ action: @escaping (PowerstationClient) async throws -> Void) {
        guard let client = client else {
            lastError = "Not connected"
            return
        }
        Task { @MainActor [weak self] in
            guard let self else { return }
            self.activeCommandCount += 1
            defer { self.activeCommandCount -= 1 }
            do {
                try await action(client)
                self.lastError = nil
            } catch {
                self.lastError = error.localizedDescription
            }
        }
    }

    // MARK: - Switches

    func setMaster(_ on: Bool) { run { try await $0.setMasterSwitch(on) } }
    func setAC(_ on: Bool) { run { try await $0.setACOutput(on) } }
    func setDC(_ on: Bool) { run { try await $0.setDCOutput(on) } }
    func setAmbientLight(_ on: Bool) { run { try await $0.setAmbientLight(on) } }
    func setBuzzer(_ on: Bool) { run { try await $0.setBuzzer(on) } }
    func setSleepMode(_ on: Bool) { run { try await $0.setSleepMode(on) } }
    func setAmpUp(_ on: Bool) { run { try await $0.setAmpUpMode(on) } }
    func setFourG(_ on: Bool) { run { try await $0.setFourGSwitch(on) } }

    // MARK: - Charging

    func setChargeLimit(_ percent: Int) { run { try await $0.setChargeLimit(percent) } }
    func setChargeSpeed(_ watts: Int) { run { try await $0.setMaxChargeWatts(watts) } }

    // MARK: - Standby

    func setKeepPoweredOn(_ enabled: Bool, screenLevel: Int) {
        run { try await $0.setKeepPoweredOn(enabled, screenLevel: screenLevel) }
    }
    func setScreenTimeout(_ level: Int, keepPoweredOn: Bool) {
        run { try await $0.setStandbyLevels(machineLevel: keepPoweredOn ? 6 : 1, screenLevel: level) }
    }

    // MARK: - LED

    func applyLED(colorId: Int, brightness: Int) {
        run { try await $0.setLEDColorAndBrightness(colorId: colorId, brightness: brightness) }
    }

    // MARK: - Power controls

    func triggerAmpUpOn() { run { try await $0.triggerAmpUpOn() } }

    /// Turning the unit off is just Master Power off — going through
    /// the same read-modify-write path as the Status tab's Master
    /// toggle, not the raw '12'/'00' command, which zeroed the whole
    /// switch register (AC, DC, Beep, Ambient Light included) instead
    /// of just the master bit.
    func triggerPowerOff() { run { try await $0.setMasterSwitch(false) } }
}
