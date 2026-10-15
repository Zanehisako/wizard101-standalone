import AppKit
import Foundation

let output = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for (name, pixels) in [("icon_16x16",16),("icon_16x16@2x",32),("icon_32x32",32),("icon_32x32@2x",64),("icon_128x128",128),("icon_128x128@2x",256),("icon_256x256",256),("icon_256x256@2x",512),("icon_512x512",512),("icon_512x512@2x",1024)] {
    let bitmap = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels, bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: bitmap)
    let ctx = NSGraphicsContext.current!.cgContext
    ctx.scaleBy(x: CGFloat(pixels)/512, y: CGFloat(pixels)/512)
    let bounds = NSRect(x: 24,y: 24,width: 464,height: 464)
    let plate = NSBezierPath(roundedRect: bounds,xRadius: 104,yRadius: 104)
    NSGradient(starting: NSColor(red: 0.30,green: 0.15,blue: 0.46,alpha: 1), ending: NSColor(red: 0.09,green: 0.08,blue: 0.21,alpha: 1))!.draw(in: plate,angle: -90)
    let gold = NSColor(red: 0.97,green: 0.76,blue: 0.35,alpha: 1)
    gold.setStroke(); plate.lineWidth = 5; plate.stroke()
    let ring = NSBezierPath(ovalIn: NSRect(x: 70,y: 70,width: 372,height: 372))
    NSColor(red: 0.97,green: 0.76,blue: 0.35,alpha: 0.45).setStroke();ring.lineWidth = 2;ring.stroke()
    let hat = NSBezierPath();hat.move(to: NSPoint(x: 151,y: 170));hat.line(to: NSPoint(x: 248,y: 386));hat.curve(to: NSPoint(x: 335,y: 360), controlPoint1: NSPoint(x: 307,y: 420), controlPoint2: NSPoint(x: 304,y: 353));hat.line(to: NSPoint(x: 292,y: 343));hat.line(to: NSPoint(x: 357,y: 170));hat.close()
    NSGradient(starting: NSColor(red: 0.35,green: 0.40,blue: 0.80,alpha: 1), ending: NSColor(red: 0.16,green: 0.13,blue: 0.43,alpha: 1))!.draw(in: hat, angle: 0)
    gold.setStroke();hat.lineWidth = 4;hat.stroke()
    let brim = NSBezierPath(ovalIn: NSRect(x: 110,y: 130,width: 292,height: 78));
    NSColor(red: 0.22,green: 0.20,blue: 0.49,alpha: 1).setFill();brim.fill();gold.setStroke();brim.lineWidth = 4;brim.stroke()
    let band = NSBezierPath();band.move(to: NSPoint(x: 159,y: 191));band.line(to: NSPoint(x: 347,y: 191));gold.setStroke();band.lineWidth = 14;band.stroke()
    func star(_ x: CGFloat,_ y: CGFloat,_ r: CGFloat) {
        let p = NSBezierPath();p.move(to:NSPoint(x:x,y:y+r));p.line(to:NSPoint(x:x+r*0.24,y:y+r*0.24));p.line(to:NSPoint(x:x+r,y:y));p.line(to:NSPoint(x:x+r*0.24,y:y-r*0.24));p.line(to:NSPoint(x:x,y:y-r));p.line(to:NSPoint(x:x-r*0.24,y:y-r*0.24));p.line(to:NSPoint(x:x-r,y:y));p.line(to:NSPoint(x:x-r*0.24,y:y+r*0.24));p.close();gold.setFill();p.fill()
    }
    star(252,284,28);star(130,350,18);star(388,316,12);star(352,409,9)
    NSGraphicsContext.restoreGraphicsState()
    try bitmap.representation(using: .png,properties: [:])!.write(to: output.appendingPathComponent(name+".png"))
}
