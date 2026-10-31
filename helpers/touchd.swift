// HomeView camera touch helper: watches the iMac's screen through a USB webcam, finds your index fingertip with Apple's
// on-device hand tracking (Vision), and sends it to the dashboard (which maps it onto the screen and turns it into taps).
// Nothing is uploaded. Frames stay in memory; one is written to the data folder when the dashboard asks (calibration,
// and a marked frame for each tap so you can check accuracy; the dashboard keeps the last 12).
import Foundation
import AVFoundation
import Vision
import CoreImage

// The dashboard port comes from server.py ("open HomeViewTouch.app --args <port>"); 8878 by default.
let port = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "8878"
let server = URL(string: "http://127.0.0.1:\(port)/touch-raw")!
// server.py launches this as "open HomeViewTouch.app --args <port> <frame path>".
let frameOut = URL(fileURLWithPath: CommandLine.arguments.count > 2 ? CommandLine.arguments[2]
                   : NSHomeDirectory() + "/Library/Application Support/HomeView/data/touch-frame.jpg")

final class Cam: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    let queue = DispatchQueue(label: "cam")
    let ci = CIContext()
    var wantSnap = false
    var lastIdle = 0.0
    var busy = false

    func start() {
        var types: [AVCaptureDevice.DeviceType] = [.builtInWideAngleCamera]
        if #available(macOS 14, *) { types.insert(.external, at: 0) } else { types.insert(.externalUnknown, at: 0) }
        let found = AVCaptureDevice.DiscoverySession(deviceTypes: types, mediaType: .video, position: .unspecified).devices
        // prefer a USB webcam over the built-in camera
        guard let dev = found.first(where: { $0.deviceType != .builtInWideAngleCamera }) ?? found.first else {
            print("no camera found"); exit(2)
        }
        print("camera:", dev.localizedName)
        session.beginConfiguration()
        session.sessionPreset = .hd1280x720
        guard let input = try? AVCaptureDeviceInput(device: dev), session.canAddInput(input) else { print("camera input failed"); exit(3) }
        session.addInput(input)
        let out = AVCaptureVideoDataOutput()
        out.alwaysDiscardsLateVideoFrames = true
        out.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA]
        out.setSampleBufferDelegate(self, queue: queue)
        session.addOutput(out)
        session.commitConfiguration()
        session.startRunning()
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sb: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let pb = CMSampleBufferGetImageBuffer(sb) else { return }
        let w = Double(CVPixelBufferGetWidth(pb)), h = Double(CVPixelBufferGetHeight(pb))
        if wantSnap {
            wantSnap = false
            let img = CIImage(cvPixelBuffer: pb)
            try? ci.writeJPEGRepresentation(of: img, to: frameOut, colorSpace: CGColorSpace(name: CGColorSpace.sRGB)!, options: [:])
        }
        let req = VNDetectHumanHandPoseRequest()
        req.maximumHandCount = 1
        try? VNImageRequestHandler(cvPixelBuffer: pb, orientation: .up).perform([req])
        var body: [String: Any] = ["w": w, "h": h, "t": Date().timeIntervalSince1970]
        if let obs = req.results?.first, let pts = try? obs.recognizedPoints(.all) {
            func put(_ k: String, _ j: VNHumanHandPoseObservation.JointName) {
                if let p = pts[j], p.confidence > 0.3 { body[k] = [p.location.x * w, (1 - p.location.y) * h, Double(p.confidence)] }
            }
            put("index", .indexTip); put("indexPIP", .indexPIP); put("thumb", .thumbTip); put("middle", .middleTip); put("wrist", .wrist)
        }
        let now = Date().timeIntervalSince1970
        if body["index"] == nil && now - lastIdle < 0.5 && !wantSnap { return }    // no hand: just a heartbeat twice a second
        if body["index"] == nil { lastIdle = now }
        if busy { return }
        busy = true
        var r = URLRequest(url: server); r.httpMethod = "POST"; r.timeoutInterval = 1.0
        r.setValue("application/json", forHTTPHeaderField: "Content-Type")
        r.httpBody = try? JSONSerialization.data(withJSONObject: body)
        URLSession.shared.dataTask(with: r) { data, _, _ in
            self.busy = false
            if let d = data, let j = try? JSONSerialization.jsonObject(with: d) as? [String: Any], (j["snap"] as? Bool) == true {
                self.queue.async { self.wantSnap = true }
            }
        }.resume()
    }
}

setvbuf(stdout, nil, _IOLBF, 0)
let sem = DispatchSemaphore(value: 0)
var allowed = false
AVCaptureDevice.requestAccess(for: .video) { ok in allowed = ok; sem.signal() }
sem.wait()
if !allowed { print("camera access not allowed"); exit(1) }
let cam = Cam()
cam.start()
RunLoop.main.run()
