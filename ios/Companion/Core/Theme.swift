import SwiftUI
import UIKit

/// The colours of the unplugged.ai web app (web/index.html), light and dark.
enum UP {
    private static func dyn(_ light: UInt32, _ dark: UInt32) -> Color {
        Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(hex: dark) : UIColor(hex: light) })
    }
    static let bg = dyn(0xFFFFFF, 0x212121)
    static let panel = dyn(0xF9F9F9, 0x171717)
    static let card = dyn(0xF7F7F8, 0x2A2A2A)
    static let ink = dyn(0x0D0D0D, 0xECECEC)
    static let muted = dyn(0x6E6E80, 0x9B9B9B)
    static let line = dyn(0xE5E5E5, 0x343434)
    static let hover = dyn(0xECECEC, 0x2A2A2A)
    static let bubble = dyn(0xF4F4F4, 0x303030)
    static let composer = dyn(0xF4F4F4, 0x303030)
    static let accent = dyn(0x0D0D0D, 0xECECEC)
    static let accentInk = dyn(0xFFFFFF, 0x212121)
    static let brand = Color(red: 240 / 255, green: 160 / 255, blue: 110 / 255)   // the floating bar of the logo
    static let ok = Color(red: 0.19, green: 0.78, blue: 0.35)
    static let warn = Color(red: 0.85, green: 0.38, blue: 0.17)
}

extension UIColor {
    convenience init(hex: UInt32) {
        self.init(red: CGFloat((hex >> 16) & 0xFF) / 255, green: CGFloat((hex >> 8) & 0xFF) / 255, blue: CGFloat(hex & 0xFF) / 255, alpha: 1)
    }
}

/// One of the web app's line icons (web/store.js, Lucide style), drawn from the vector asset "i.<name>".
struct Icon: View {
    let name: String
    var size: CGFloat = 20
    init(_ name: String, size: CGFloat = 20) { self.name = name; self.size = size }
    var body: some View {
        Image("i.\(name)").resizable().renderingMode(.template).scaledToFit().frame(width: size, height: size)
    }
}

/// The web app's small spinner (a ring with a gap).
struct Spinner: View {
    var size: CGFloat = 12
    @State private var turn = false
    var body: some View {
        Circle().trim(from: 0, to: 0.75).stroke(UP.muted, style: StrokeStyle(lineWidth: 2, lineCap: .round))
            .frame(width: size, height: size)
            .rotationEffect(.degrees(turn ? 360 : 0))
            .onAppear { withAnimation(.linear(duration: 0.8).repeatForever(autoreverses: false)) { turn = true } }
    }
}

/// The web app's switch: a 38 by 22 track, white knob; on: ink track, dark knob.
struct UPSwitch: View {
    @Binding var isOn: Bool
    var body: some View {
        Button { withAnimation(.easeOut(duration: 0.15)) { isOn.toggle() } } label: {
            ZStack(alignment: isOn ? .trailing : .leading) {
                Capsule().fill(isOn ? UP.accent : UP.line).frame(width: 38, height: 22)
                Circle().fill(isOn ? UP.accentInk : Color.white).frame(width: 18, height: 18).padding(2)
            }
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(.isToggle)
        .accessibilityValue(isOn ? "on" : "off")
    }
}

/// A web-app style card (.card): card background, hairline border, rounded corners.
struct CardStyle: ViewModifier {
    var padding: CGFloat = 14
    func body(content: Content) -> some View {
        content
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 16).fill(UP.card))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(UP.line, lineWidth: 1))
    }
}

extension View {
    func upCard(padding: CGFloat = 14) -> some View { modifier(CardStyle(padding: padding)) }

    /// Input fields as in the web app.
    func upField() -> some View {
        self.font(.system(size: 15)).padding(.horizontal, 12).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 10).fill(UP.bg))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(UP.line, lineWidth: 1))
    }
}

/// Small uppercase card headings ("MAKE MUSIC").
struct CardTitle: View {
    let text: String
    init(_ text: String) { self.text = text }
    var body: some View {
        Text(text.uppercased()).font(.system(size: 13, weight: .semibold)).tracking(0.78).foregroundStyle(UP.muted)
    }
}

/// "Label / small hint" pair above a field.
struct FieldLabel: View {
    let title: String
    var hint: String?
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(title).font(.system(size: 14, weight: .semibold)).foregroundStyle(UP.ink)
            if let hint { Text(hint).font(.system(size: 12.5)).foregroundStyle(UP.muted).fixedSize(horizontal: false, vertical: true) }
        }
    }
}

/// Primary (filled) and secondary (outlined) buttons of the web app.
struct UPButton: ButtonStyle {
    var primary = false
    var wide = false
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 14, weight: primary ? .semibold : .regular))
            .padding(.horizontal, 14).padding(.vertical, primary ? 11 : 8)
            .frame(maxWidth: wide ? .infinity : nil)
            .foregroundStyle(primary ? UP.accentInk : UP.ink)
            .background(RoundedRectangle(cornerRadius: 10).fill(primary ? UP.accent : UP.bubble))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(primary ? Color.clear : UP.line, lineWidth: 1))
            .opacity(configuration.isPressed ? 0.75 : 1)
    }
}

/// Liquid Glass dropdown: a pill that opens a glass panel of options with a title and an optional description each.
struct GlassSelect<T: Hashable>: View {
    let options: [(value: T, title: String, detail: String?)]
    @Binding var selection: T
    var placeholder = "Choose"
    var wide = true

    var body: some View {
        Menu {
            ForEach(options.indices, id: \.self) { i in
                let o = options[i]
                Button {
                    selection = o.value
                } label: {
                    if let d = o.detail, !d.isEmpty {
                        Label { Text(o.title); Text(d) } icon: { if o.value == selection { Image("i.check") } }
                    } else {
                        Label { Text(o.title) } icon: { if o.value == selection { Image("i.check") } }
                    }
                }
            }
        } label: {
            HStack {
                Text(options.first { $0.value == selection }?.title ?? placeholder).foregroundStyle(UP.ink).lineLimit(1)
                if wide { Spacer() }
                Icon("chevron", size: 16).foregroundStyle(UP.muted)
            }
            .font(.system(size: 14))
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxWidth: wide ? .infinity : nil)
            .glassEffect(.regular.interactive(), in: RoundedRectangle(cornerRadius: 12))
        }
        .menuOrder(.fixed)
    }
}

/// The segmented control of the web settings (System / Light / Dark).
struct UPSegmented<T: Hashable>: View {
    let options: [(T, String)]
    @Binding var selection: T
    @Namespace private var ns

    var body: some View {
        HStack(spacing: 0) {
            ForEach(options.indices, id: \.self) { i in
                let (v, t) = options[i]
                Button { withAnimation(.snappy(duration: 0.2)) { selection = v } } label: {
                    Text(t).font(.system(size: 13))
                        .foregroundStyle(selection == v ? UP.ink : UP.muted)
                        .frame(maxWidth: .infinity).padding(.vertical, 7)
                        .background {
                            if selection == v { RoundedRectangle(cornerRadius: 8).fill(UP.hover).matchedGeometryEffect(id: "seg", in: ns) }
                        }
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 10).fill(UP.bg))
    }
}

/// A settings row: title and description on the left, a control on the right or below.
struct SettingRow<Control: View>: View {
    let title: String
    var detail: String?
    var stacked = false
    @ViewBuilder var control: () -> Control

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if stacked {
                FieldLabel(title: title, hint: detail)
                control()
            } else {
                HStack(alignment: .center, spacing: 12) {
                    FieldLabel(title: title, hint: detail)
                    Spacer(minLength: 8)
                    control()
                }
            }
        }
        .padding(.vertical, 14)
        .overlay(alignment: .bottom) { Rectangle().fill(UP.line).frame(height: 1) }
    }
}

extension Dictionary where Key == String, Value == Any {
    func str(_ k: String) -> String? { self[k] as? String }
    func int(_ k: String) -> Int? { (self[k] as? Int) ?? (self[k] as? Double).map { Int($0) } }
    func dbl(_ k: String) -> Double? { (self[k] as? Double) ?? (self[k] as? Int).map { Double($0) } }
    func bool(_ k: String) -> Bool? { self[k] as? Bool }
    func dicts(_ k: String) -> [[String: Any]] { self[k] as? [[String: Any]] ?? [] }
}
