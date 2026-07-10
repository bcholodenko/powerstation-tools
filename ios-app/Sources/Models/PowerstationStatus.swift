//
//  PowerstationStatus.swift
//  Powerstation
//
//  Direct port of parse_status_93_payload() from powerstation_control.py.
//  Parses the short status format (command '93', 23 bytes = 46 hex chars).
//

import Foundation

struct PowerstationStatus: Equatable {
    let batteryPercent: Int?
    let remainingOutputMinutes: Int?
    let remainingInputMinutes: Int?
    let acInputWatts: Int?
    let dcInputWatts: Int?
    let acOutputWatts: Int?
    let dc12vWatts: Int?
    let dcPortWatts: [Int?]
    let dcOutputWatts: Int?
    let ambientColor: Int?          // 1-10 palette index (lower 5 bits)
    let ambientLightness: Int?      // 0-100
    let switches: [String: Bool]?   // master, ac, dc, buzzer, ambient_light, ac_hz, plus 2 unlabeled bits
    let ampUp: Bool?
    let sleepMode: Bool?
    let acVoltageHigh: Bool?
    let pvInputDetected: Bool?
    let chargeSpeedWatts: Int?
    let temperatureC: Double?
    let ampByteRaw: Int?            // raw byte backing ampUp/sleepMode/chargeSpeed, needed to flip one bit at a time
    let rawHex: String

    init?(hexPayload data: String) {
        guard data.count >= 2 else { return nil }
        rawHex = data

        func hx(_ start: Int, _ end: Int) -> Int? {
            guard start >= 0, end <= data.count, start < end else { return nil }
            let s = data.index(data.startIndex, offsetBy: start)
            let e = data.index(data.startIndex, offsetBy: end)
            return Int(data[s..<e], radix: 16)
        }
        func noSentinel(_ v: Int?) -> Int? { v == 0xFFFF ? nil : v }

        batteryPercent = hx(0, 2)
        remainingOutputMinutes = noSentinel(hx(2, 6))
        remainingInputMinutes = noSentinel(hx(6, 10))
        acInputWatts = hx(10, 14)
        dcInputWatts = hx(14, 18)
        acOutputWatts = hx(18, 22)
        dc12vWatts = hx(22, 26)
        dcPortWatts = [hx(26, 28), hx(28, 30), hx(30, 32), hx(32, 34)]

        let dcParts = ([dc12vWatts] + dcPortWatts).compactMap { $0 }
        dcOutputWatts = dcParts.isEmpty ? nil : dcParts.reduce(0, +)

        if let raw = hx(34, 36) {
            ambientColor = raw & 0x1F   // only the lower 5 bits are meaningful
        } else {
            ambientColor = nil
        }
        ambientLightness = hx(36, 38)

        if let swByte = hx(38, 40) {
            // MSB(index0)=ac_hz ... LSB(index7)=master.
            let names = ["ac_hz", "unknown_bit1", "unknown_bit2", "ambient_light",
                         "buzzer", "dc", "ac", "master"]
            var dict: [String: Bool] = [:]
            for (i, name) in names.enumerated() {
                dict[name] = ((swByte >> (7 - i)) & 1) == 1
            }
            switches = dict
        } else {
            switches = nil
        }

        if let ampByte = hx(40, 42) {
            ampByteRaw = ampByte
            ampUp = (ampByte & 0x01) != 0
            sleepMode = ((ampByte >> 1) & 0x01) != 0
            acVoltageHigh = ((ampByte >> 3) & 0x01) != 0
            pvInputDetected = ((ampByte >> 4) & 0x01) != 0
            let level = (ampByte >> 5) & 0x07
            let levelToWatts = [1: 300, 2: 500, 3: 800, 4: 1200, 5: 1800]
            chargeSpeedWatts = levelToWatts[level]
        } else {
            ampByteRaw = nil
            ampUp = nil
            sleepMode = nil
            acVoltageHigh = nil
            pvInputDetected = nil
            chargeSpeedWatts = nil
        }

        if let tempRaw = hx(42, 46) {
            let raw = (Double(tempRaw) - 2731.0) / 10.0
            temperatureC = (raw * 10).rounded() / 10
        } else {
            temperatureC = nil
        }
    }
}
