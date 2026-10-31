// Make a person-segmentation mask (white = person) for each photo, using macOS Vision.
// Usage: personmask <photo-dir> <out-dir>
import Foundation
import Vision
import CoreImage
import ImageIO
import UniformTypeIdentifiers

let args = CommandLine.arguments
guard args.count == 3 else { print("usage: personmask <photo-dir> <out-dir>"); exit(2) }
let inDir = URL(fileURLWithPath: args[1]), outDir = URL(fileURLWithPath: args[2])
let ctx = CIContext()
let exts = Set(["jpg", "jpeg", "png", "heic"])
let files = (try? FileManager.default.contentsOfDirectory(at: inDir, includingPropertiesForKeys: nil)) ?? []
for f in files.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) where exts.contains(f.pathExtension.lowercased()) {
    let out = outDir.appendingPathComponent(f.lastPathComponent + ".mask.png")
    if FileManager.default.fileExists(atPath: out.path) { continue }
    guard var img = CIImage(contentsOf: f, options: [.applyOrientationProperty: true]) else { print("skip", f.lastPathComponent); continue }
    img = img.transformed(by: CGAffineTransform(translationX: -img.extent.origin.x, y: -img.extent.origin.y))
    let req = VNGeneratePersonSegmentationRequest()
    req.qualityLevel = .accurate
    req.outputPixelFormat = kCVPixelFormatType_OneComponent8
    let handler = VNImageRequestHandler(ciImage: img, options: [:])
    do { try handler.perform([req]) } catch { print("fail", f.lastPathComponent, error); continue }
    guard let buf = req.results?.first?.pixelBuffer else { print("none", f.lastPathComponent); continue }
    var mask = CIImage(cvPixelBuffer: buf)
    let sx = img.extent.width / mask.extent.width, sy = img.extent.height / mask.extent.height
    mask = mask.transformed(by: CGAffineTransform(scaleX: sx, y: sy))
    // Scale down to <= 1400 px on the long side to keep files small.
    let long = max(img.extent.width, img.extent.height), k = min(1.0, 1400.0 / long)
    mask = mask.transformed(by: CGAffineTransform(scaleX: k, y: k))
    let rect = CGRect(x: 0, y: 0, width: (img.extent.width * k).rounded(), height: (img.extent.height * k).rounded())
    guard let cg = ctx.createCGImage(mask, from: rect, format: .L8, colorSpace: CGColorSpaceCreateDeviceGray()) else { continue }
    guard let dest = CGImageDestinationCreateWithURL(out as CFURL, UTType.png.identifier as CFString, 1, nil) else { continue }
    CGImageDestinationAddImage(dest, cg, nil); CGImageDestinationFinalize(dest)
    print("ok", f.lastPathComponent)
}
