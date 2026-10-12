// The OpenAI key, in the keychain (it never goes into a file).
import AppKit
import AmadeusKit
import Foundation
import Observation
import Security

enum Keychain {
    private static let service = "io.github.amadeusdmx.app"
    private static let oldService = "io.github.decisivelightning.app"   // before the rename to Amadeus DMX

    static var openAIKey: String? {
        get {
            if let key = read(service) { return key }
            guard let old = read(oldService) else { return nil }
            openAIKey = old   // saved before the rename: moves to the new name
            return old
        }
        set {
            let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                    kSecAttrAccount as String: "OPENAI_API_KEY"]
            SecItemDelete(q as CFDictionary)
            if let v = newValue, !v.isEmpty {
                var add = q
                add[kSecValueData as String] = Data(v.utf8)
                SecItemAdd(add as CFDictionary, nil)
            }
        }
    }

    private static func read(_ service: String) -> String? {
        var out: AnyObject?
        let q: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
                                kSecAttrAccount as String: "OPENAI_API_KEY", kSecReturnData as String: true]
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let d = out as? Data else { return nil }
        return String(data: d, encoding: .utf8)
    }
}
