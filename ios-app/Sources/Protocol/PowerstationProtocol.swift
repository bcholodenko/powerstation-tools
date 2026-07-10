//
//  PowerstationProtocol.swift
//  Powerstation
//
//  Direct port of the framing/CRC logic from powerstation_control.py.
//  Message framing: AA55 + length(4 hex) + serial(4 hex) + command(2 hex)
//  + data + CRC16-IBM(4 hex) + CC33. All fields uppercase hex, sent as
//  plain ASCII text over the TCP socket (not raw binary).
//

import Foundation

enum PowerstationProtocol {

    enum Encoding {
        case base2   // data is already a hex string
        case ascii   // data is a plain string to be hex-encoded
    }

    // CRC16-IBM lookup table — identical to CRC_TABLE in powerstation_control.py.
    static let crcTable: [Int] = [
        0,49345,49537,320,49921,960,640,49729,50689,1728,1920,51009,1280,50625,50305,1088,
        52225,3264,3456,52545,3840,53185,52865,3648,2560,51905,52097,2880,51457,2496,2176,
        51265,55297,6336,6528,55617,6912,56257,55937,6720,7680,57025,57217,8000,56577,7616,
        7296,56385,5120,54465,54657,5440,55041,6080,5760,54849,53761,4800,4992,54081,4352,
        53697,53377,4160,61441,12480,12672,61761,13056,62401,62081,12864,13824,63169,63361,
        14144,62721,13760,13440,62529,15360,64705,64897,15680,65281,16320,16000,65089,64001,
        15040,15232,64321,14592,63937,63617,14400,10240,59585,59777,10560,60161,11200,10880,
        59969,60929,11968,12160,61249,11520,60865,60545,11328,58369,9408,9600,58689,9984,
        59329,59009,9792,8704,58049,58241,9024,57601,8640,8320,57409,40961,24768,24960,
        41281,25344,41921,41601,25152,26112,42689,42881,26432,42241,26048,25728,42049,
        27648,44225,44417,27968,44801,28608,28288,44609,43521,27328,27520,43841,26880,
        43457,43137,26688,30720,47297,47489,31040,47873,31680,31360,47681,48641,32448,
        32640,48961,32000,48577,48257,31808,46081,29888,30080,46401,30464,47041,46721,
        30272,29184,45761,45953,29504,45313,29120,28800,45121,20480,37057,37249,20800,
        37633,21440,21120,37441,38401,22208,22400,38721,21760,38337,38017,21568,39937,
        23744,23936,40257,24320,40897,40577,24128,23040,39617,39809,23360,39169,22976,
        22656,38977,34817,18624,18816,35137,19200,35777,35457,19008,19968,36545,36737,
        20288,36097,19904,19584,35905,17408,33985,34177,17728,34561,18368,18048,34369,
        33281,17088,17280,33601,16640,33217,32897,16448
    ]

    /// CRC16-IBM over a hex string (e.g. "AA550010..."). Returns 4-char uppercase hex.
    static func crc16IBM(_ hexString: String) -> String {
        guard hexString.count % 2 == 0 else { return "0000" }
        var crc = 0
        var idx = hexString.startIndex
        while idx < hexString.endIndex {
            let next = hexString.index(idx, offsetBy: 2)
            let b = Int(hexString[idx..<next], radix: 16) ?? 0
            let tableIndex = (crc ^ b) & 0xFF
            crc = ((crc >> 8) & 0xFF) ^ crcTable[tableIndex]
            idx = next
        }
        return String(format: "%04X", UInt16(crc & 0xFFFF))
    }

    /// Auto-increment a 4-hex-char serial, wrapping 0xFFFF to 0x0000.
    static func autoIncrementSerial(_ serial: String) -> String {
        guard serial.count == 4, let n = Int(serial, radix: 16) else { return "0001" }
        if n == 0xFFFF { return "0000" }
        return pad4(String(format: "%X", UInt16((n + 1) & 0xFFFF)))
    }

    static func pad4(_ s: String) -> String {
        var r = s
        while r.count < 4 { r = "0" + r }
        return r
    }

    static func asciiToHex(_ s: String) -> String {
        s.unicodeScalars.map { String(format: "%X", $0.value) }.joined()
    }

    /// Build a full frame: AA55 + length + serial + command + data + CRC16 + CC33.
    static func buildFrame(serial: String, command: String, data: String, encoding: Encoding) -> String {
        let dataHex: String
        let lengthValue: Int
        switch encoding {
        case .base2:
            dataHex = data
            lengthValue = 11 + data.count / 2
        case .ascii:
            dataHex = asciiToHex(data)
            lengthValue = 11 + dataHex.count
        }
        let lengthField = pad4(String(format: "%X", UInt16(clamping: lengthValue)))
        let msgWithoutCRC = "AA55" + lengthField + serial + command + dataHex
        let crc = crc16IBM(msgWithoutCRC)
        return msgWithoutCRC + crc + "CC33"
    }

    /// Strip the AA55...CC33 envelope. Returns (command, data) or nil if malformed.
    static func parseResponseFrame(_ response: String) -> (command: String, data: String)? {
        let r = response.trimmingCharacters(in: .whitespacesAndNewlines)
        guard r.count >= 22, r.hasPrefix("AA55"), r.hasSuffix("CC33") else { return nil }
        let cmdStart = r.index(r.startIndex, offsetBy: 12)
        let cmdEnd = r.index(r.startIndex, offsetBy: 14)
        let dataEnd = r.index(r.endIndex, offsetBy: -8)
        guard cmdEnd <= dataEnd else { return nil }
        return (String(r[cmdStart..<cmdEnd]), String(r[cmdEnd..<dataEnd]))
    }

    /// Validate a frame's CRC before trusting its contents.
    static func frameCRCOK(_ frameText: String) -> Bool {
        guard frameText.count >= 22, frameText.hasPrefix("AA55"), frameText.hasSuffix("CC33") else { return false }
        let bodyEnd = frameText.index(frameText.endIndex, offsetBy: -8)
        let crcEnd = frameText.index(frameText.endIndex, offsetBy: -4)
        let body = String(frameText[frameText.startIndex..<bodyEnd])
        let embeddedCRC = String(frameText[bodyEnd..<crcEnd])
        return crc16IBM(body) == embeddedCRC.uppercased()
    }

    /// Decode a short ACK payload returned for a control command.
    static func parseAck(_ data: String) -> String {
        switch data.uppercased() {
        case "55": return "success"
        case "CC": return "fail"
        case "33": return "error"
        default: return "unknown"
        }
    }

    /// Left-pad a binary string with zeros to `width` bits.
    static func binaryPadded(_ value: Int, width: Int) -> String {
        var s = String(value, radix: 2)
        while s.count < width { s = "0" + s }
        return s
    }
}
