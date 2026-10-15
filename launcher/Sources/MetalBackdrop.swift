import SwiftUI
import MetalKit

final class SpiralRenderer: NSObject, MTKViewDelegate {
    let device: MTLDevice
    let queue: MTLCommandQueue
    let pipeline: MTLRenderPipelineState
    init(device: MTLDevice, shaderURL: URL) throws {
        self.device = device
        guard let queue = device.makeCommandQueue() else { throw LauncherError.message("Metal command queue is unavailable.") }
        self.queue = queue
        let source = try String(contentsOf: shaderURL, encoding: .utf8)
        let library = try device.makeLibrary(source: source, options: nil)
        let descriptor = MTLRenderPipelineDescriptor()
        descriptor.vertexFunction = library.makeFunction(name: "spiralVertex")
        descriptor.fragmentFunction = library.makeFunction(name: "spiralFragment")
        descriptor.colorAttachments[0].pixelFormat = .bgra8Unorm
        pipeline = try device.makeRenderPipelineState(descriptor: descriptor)
        super.init()
    }
    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) { view.needsDisplay = true }
    func draw(in view: MTKView) {
        guard let drawable = view.currentDrawable, let pass = view.currentRenderPassDescriptor,
              let command = queue.makeCommandBuffer(), let encoder = command.makeRenderCommandEncoder(descriptor: pass) else { return }
        encode(encoder, width: Int(view.drawableSize.width), height: Int(view.drawableSize.height))
        encoder.endEncoding()
        command.present(drawable)
        command.commit()
    }
    func encode(_ encoder: MTLRenderCommandEncoder, width: Int, height: Int) {
        encoder.setRenderPipelineState(pipeline)
        var size = SIMD2<Float>(Float(width), Float(height))
        encoder.setFragmentBytes(&size, length: MemoryLayout<SIMD2<Float>>.stride, index: 0)
        encoder.drawPrimitives(type: .triangle, vertexStart: 0, vertexCount: 3)
    }
}

struct MetalBackdrop: NSViewRepresentable {
    let renderer: SpiralRenderer?
    func makeNSView(context: Context) -> MTKView {
        let view = MTKView(frame: .zero, device: renderer?.device)
        view.colorPixelFormat = .bgra8Unorm
        view.clearColor = MTLClearColor(red: 0.025, green: 0.03, blue: 0.07, alpha: 1)
        // Render on exposure/resize only: no idle frame loop or animation timer.
        view.isPaused = true
        view.enableSetNeedsDisplay = true
        view.delegate = renderer
        return view
    }
    func updateNSView(_ view: MTKView, context: Context) { view.needsDisplay = true }
}
