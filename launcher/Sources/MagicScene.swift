import SwiftUI

// Original vector artwork; no game assets, downloads or persistent GPU loop.
struct MagicScene: View {
    let animated: Bool
    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 24.0, paused: !animated)) { timeline in
            Canvas { context, size in
                let time = animated ? timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 3600) : 0
                context.scaleBy(x: size.width / 556, y: size.height / 608)
                paint(&context, time: time)
            }.drawingGroup()
        }
    }
    private func paint(_ c: inout GraphicsContext, time t: Double) {
        let full = Path(CGRect(x: 0, y: 0, width: 556, height: 608))
        c.fill(full, with: .linearGradient(Gradient(colors: [Color(red: 0.12, green: 0.08, blue: 0.26), Color(red: 0.23, green: 0.10, blue: 0.36), Color(red: 0.09, green: 0.10, blue: 0.22)]), startPoint: .zero, endPoint: CGPoint(x: 500, y: 600)))
        c.fill(full, with: .radialGradient(Gradient(colors: [Color(red: 0.35, green: 0.26, blue: 0.65).opacity(0.7), .clear]), center: CGPoint(x: 279, y: 300), startRadius: 15, endRadius: 250))
        for i in 0..<90 {
            let x = Double((i * 137 + 41) % 533) + 10
            let y = Double((i * 79 + 23) % 360) + 50
            let twinkle = 0.45 + 0.30 * sin(t * 1.2 + Double(i) * 2.7)
            let radius = i % 7 == 0 ? 1.6 : 0.8
            c.fill(Path(ellipseIn: CGRect(x: x, y: y, width: radius * 2, height: radius * 2)), with: .color(Color(red: 1, green: 0.90, blue: 0.65).opacity(twinkle)))
            if i % 13 == 0 { star(&c, x: x + radius, y: y + radius, radius: 4, opacity: twinkle) }
        }
        // Crescent moon over the distant spires.
        c.fill(Path(ellipseIn: CGRect(x: 445, y: 153, width: 34, height: 34)), with: .color(Color(red: 0.94, green: 0.88, blue: 0.72)))
        c.fill(Path(ellipseIn: CGRect(x: 454, y: 147, width: 32, height: 32)), with: .color(Color(red: 0.17, green: 0.10, blue: 0.30)))
        let center = CGPoint(x: 281, y: 291)
        let portal = Path(ellipseIn: CGRect(x: 179, y: 189, width: 204, height: 204))
        c.fill(portal, with: .radialGradient(Gradient(colors: [Color(red: 0.48, green: 0.57, blue: 0.90).opacity(0.35), Color(red: 0.22, green: 0.19, blue: 0.50).opacity(0.3), Color(red: 0.74, green: 0.41, blue: 0.80).opacity(0.12)]), center: center, startRadius: 0, endRadius: 102))
        var glow = c; glow.addFilter(.blur(radius: 12))
        glow.stroke(portal, with: .color(Color(red: 0.65, green: 0.38, blue: 0.97).opacity(0.8)), lineWidth: 12)
        c.stroke(portal, with: .color(Color(red: 0.99, green: 0.76, blue: 0.39).opacity(0.8)), lineWidth: 1.5)
        c.stroke(Path(ellipseIn: CGRect(x: 169, y: 179, width: 224, height: 224)), with: .color(Color(red: 0.99, green: 0.76, blue: 0.39).opacity(0.45)), lineWidth: 0.7)
        for i in 0..<32 {
            let a = Double(i) * .pi / 16 + t * 0.025
            let p1 = CGPoint(x: 281 + cos(a) * 108, y: 291 + sin(a) * 108)
            let p2 = CGPoint(x: 281 + cos(a) * (i % 4 == 0 ? 120 : 113), y: 291 + sin(a) * (i % 4 == 0 ? 120 : 113))
            var mark = Path(); mark.move(to: p1); mark.addLine(to: p2)
            c.stroke(mark, with: .color(Color(red: 1, green: 0.80, blue: 0.45).opacity(0.7)), lineWidth: 1)
        }
        for arm in 0..<3 {
            var spiral = Path()
            for i in 0...140 {
                let r = Double(i) * 0.60
                let a = Double(i) * 0.057 + Double(arm) * .pi * 2 / 3 + t * 0.08
                let p = CGPoint(x: 281 + cos(a) * r, y: 291 + sin(a) * r)
                if i == 0 { spiral.move(to: p) } else { spiral.addLine(to: p) }
            }
            c.stroke(spiral, with: .color(Color(red: 0.78, green: 0.70, blue: 1).opacity(0.23)), lineWidth: 1.2)
        }
        star(&c, x: 281, y: 291, radius: 17, opacity: 0.9)
        for i in 0..<12 {
            let a = Double(i) * .pi / 6 + t * 0.12
            let r = 135.0 + 11 * sin(Double(i) * 1.7 + t * 0.3)
            star(&c, x: 281 + cos(a) * r, y: 291 + sin(a) * r * 0.78, radius: i % 3 == 0 ? 4 : 2, opacity: 0.7)
        }
        // Distant hills and floating islands.
        fill(&c, [(0,427),(55,390),(102,420),(145,378),(193,425),(270,400),(360,416),(420,376),(475,403),(556,390),(556,608),(0,608)], color: Color(red: 0.15, green: 0.13, blue: 0.30))
        fill(&c, [(49,314),(101,305),(133,316),(93,345),(77,339)], color: Color(red: 0.25, green: 0.20, blue: 0.39))
        fill(&c, [(427,331),(469,320),(500,330),(466,352),(451,344)], color: Color(red: 0.25, green: 0.20, blue: 0.39))
        tower(&c, x: 80, y: 279, width: 19, height: 31, roof: 21, lit: false)
        tower(&c, x: 456, y: 293, width: 16, height: 32, roof: 19, lit: false)
        // The academy rises out of the clouds, with warm candlelit windows.
        let stone = Color(red: 0.27, green: 0.26, blue: 0.42)
        c.fill(Path(CGRect(x: 169, y: 373, width: 224, height: 101)), with: .color(stone))
        c.fill(Path(CGRect(x: 213, y: 348, width: 136, height: 120)), with: .color(Color(red: 0.31, green: 0.29, blue: 0.46)))
        tower(&c, x: 158, y: 353, width: 36, height: 120, roof: 47, lit: true)
        tower(&c, x: 367, y: 352, width: 36, height: 121, roof: 47, lit: true)
        tower(&c, x: 224, y: 326, width: 30, height: 149, roof: 52, lit: true)
        tower(&c, x: 309, y: 325, width: 30, height: 150, roof: 52, lit: true)
        tower(&c, x: 267, y: 316, width: 29, height: 111, roof: 60, lit: true)
        // Central arched doorway and tiled bridge.
        let door = Path(roundedRect: CGRect(x: 260, y: 417, width: 43, height: 64), cornerRadius: 21)
        c.fill(door, with: .linearGradient(Gradient(colors: [Color(red: 0.94, green: 0.70, blue: 0.34), Color(red: 0.71, green: 0.37, blue: 0.30)]), startPoint: CGPoint(x: 281, y: 418), endPoint: CGPoint(x: 281, y: 480)))
        c.stroke(door, with: .color(Color(red: 0.51, green: 0.40, blue: 0.47)), lineWidth: 5)
        fill(&c, [(262,477),(301,477),(336,516),(226,516)], color: Color(red: 0.48, green: 0.37, blue: 0.49))
        for i in 0..<5 {
            let y = 479.0 + Double(i) * 8
            var p = Path(); p.move(to: CGPoint(x: 261 - Double(i) * 7, y: y)); p.addLine(to: CGPoint(x: 302 + Double(i) * 7, y: y))
            c.stroke(p, with: .color(Color(red: 0.69, green: 0.54, blue: 0.51).opacity(0.6)), lineWidth: 1)
        }
        for x in [205.0, 354.0] {
            for y in [386.0, 413.0, 440.0] { window(&c, x: x, y: y) }
        }
        // Soft foreground clouds.
        var clouds = c; clouds.addFilter(.blur(radius: 16))
        for i in 0..<8 {
            let x = Double(i) * 78 - 30 + sin(t * 0.04 + Double(i)) * 7
            clouds.fill(Path(ellipseIn: CGRect(x: x, y: 478 + Double(i % 3) * 9, width: 130, height: 33)), with: .color(Color(red: 0.37, green: 0.29, blue: 0.52).opacity(0.55)))
        }
        c.fill(Path(CGRect(x: 0, y: 497, width: 556, height: 111)), with: .linearGradient(Gradient(colors: [.clear, Color(red: 0.10, green: 0.055, blue: 0.19)]), startPoint: CGPoint(x: 0, y: 497), endPoint: CGPoint(x: 0, y: 575)))
    }
    private func fill(_ c: inout GraphicsContext, _ points: [(Double, Double)], color: Color) {
        var p = Path(); for (i, point) in points.enumerated() {
            if i == 0 { p.move(to: CGPoint(x: point.0, y: point.1)) } else { p.addLine(to: CGPoint(x: point.0, y: point.1)) }
        }; p.closeSubpath(); c.fill(p, with: .color(color))
    }
    private func star(_ c: inout GraphicsContext, x: Double, y: Double, radius r: Double, opacity: Double) {
        fill(&c, [(x,y-r),(x+r*0.23,y-r*0.23),(x+r,y),(x+r*0.23,y+r*0.23),(x,y+r),(x-r*0.23,y+r*0.23),(x-r,y),(x-r*0.23,y-r*0.23)], color: Color(red: 1, green: 0.84, blue: 0.54).opacity(opacity))
    }
    private func window(_ c: inout GraphicsContext, x: Double, y: Double) {
        let p = Path(roundedRect: CGRect(x: x, y: y, width: 7, height: 12), cornerRadius: 3)
        var glow = c; glow.addFilter(.blur(radius: 4)); glow.fill(p, with: .color(.orange.opacity(0.7)))
        c.fill(p, with: .color(Color(red: 1, green: 0.80, blue: 0.39)))
    }
    private func tower(_ c: inout GraphicsContext, x: Double, y: Double, width w: Double, height h: Double, roof: Double, lit: Bool) {
        c.fill(Path(CGRect(x: x, y: y, width: w, height: h)), with: .linearGradient(Gradient(colors: [Color(red: 0.44, green: 0.39, blue: 0.56), Color(red: 0.24, green: 0.22, blue: 0.38)]), startPoint: CGPoint(x: x,y: y), endPoint: CGPoint(x: x+w,y: y+h)))
        fill(&c, [(x-5,y),(x+w/2,y-roof),(x+w+5,y)], color: Color(red: 0.19, green: 0.11, blue: 0.33))
        var edge = Path(); edge.move(to: CGPoint(x: x-5,y: y)); edge.addLine(to: CGPoint(x: x+w/2,y: y-roof)); edge.addLine(to: CGPoint(x: x+w+5,y: y))
        c.stroke(edge, with: .color(Color(red: 0.73, green: 0.52, blue: 0.42)), lineWidth: 1)
        if lit { window(&c, x: x+w/2-3, y: y+16); window(&c, x: x+w/2-3, y: y+45) }
        star(&c, x: x+w/2,y: y-roof, radius: 3, opacity: 0.8)
    }
}
