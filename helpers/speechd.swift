// On-device speech recognition helper (HomeViewSpeech.app). Reads 16 kHz mono 16-bit PCM from voice.py, sends back JSON lines:
// {"t":"partial","text":...} while listening and {"t":"final","text":...} when a phrase ends.
// Built by helpers/build.sh; voice.py launches it. macOS asks once for Speech Recognition permission.
import Foundation
import Speech
import AVFoundation

// Talks to voice.py over 127.0.0.1 (port from the first argument, 8880 by default): PCM in, JSON lines out
// (so this can be a real app that macOS can ask permission for).
let port: UInt16 = CommandLine.arguments.count > 1 ? (UInt16(CommandLine.arguments[1]) ?? 8880) : 8880
var sock: Int32 = -1
func connectVoice() -> Bool {
    let fd = socket(AF_INET, SOCK_STREAM, 0)
    var addr = sockaddr_in(); addr.sin_family = sa_family_t(AF_INET); addr.sin_port = in_port_t(port).bigEndian; addr.sin_addr.s_addr = inet_addr("127.0.0.1")
    let ok = withUnsafePointer(to: &addr) { $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(fd, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) } } == 0
    if !ok { close(fd); return false }
    sock = fd; return true
}
let outLock = NSLock()
func emit(_ obj: [String: Any]) {
    guard let d = try? JSONSerialization.data(withJSONObject: obj), var s = String(data: d, encoding: .utf8) else { return }
    s += "\n"
    outLock.lock(); defer { outLock.unlock() }
    s.withCString { p in _ = write(sock, p, strlen(p)) }
}
var tries = 0
while !connectVoice() { tries += 1; if tries > 60 { exit(3) }; Thread.sleep(forTimeInterval: 1) }
let sem = DispatchSemaphore(value: 0)
var authorized = false
SFSpeechRecognizer.requestAuthorization { st in authorized = (st == .authorized); sem.signal() }
sem.wait()
guard authorized, let rec = SFSpeechRecognizer(locale: Locale(identifier: "en-US")), rec.isAvailable else {
    emit(["t": "error", "text": "speech recognition not authorized or unavailable"]); exit(2)
}
let fmt = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
var req: SFSpeechAudioBufferRecognitionRequest!
var task: SFSpeechRecognitionTask?
var lastText = ""
var lastChange = Date()
let lock = NSLock()
var gen = 0          // each recognition session gets a number; results from an old (cancelled) session are ignored
// Words to expect (wake word, assistant name, device names). voice.py writes them from config.json.
let hintsFile = NSHomeDirectory() + "/Library/Application Support/HomeView/speech-hints.txt"
let hints: [String] = ((try? String(contentsOfFile: hintsFile, encoding: .utf8)) ?? "Hey Apple\nHomeView")
    .split(separator: "\n").map { String($0) }.filter { !$0.isEmpty }

func start() {
    let r0 = SFSpeechAudioBufferRecognitionRequest()
    r0.shouldReportPartialResults = true
    r0.contextualStrings = hints
    if #available(macOS 10.15, *) { r0.requiresOnDeviceRecognition = rec.supportsOnDeviceRecognition }
    if #available(macOS 13, *) { r0.addsPunctuation = true }
    lock.lock(); gen += 1; let myGen = gen; req = r0; lock.unlock()
    task = rec.recognitionTask(with: r0) { result, error in
        lock.lock(); defer { lock.unlock() }
        if myGen != gen { return }
        if let r = result {
            let text = r.bestTranscription.formattedString
            if text != lastText { lastText = text; lastChange = Date() }
            emit(["t": r.isFinal ? "final" : "partial", "text": text])
            if r.isFinal { lastText = ""; restart() }
        }
        if error != nil { emit(["t": "reset", "text": lastText]); lastText = ""; restart() }
    }
}
func restart() { DispatchQueue.main.async { task?.cancel(); start() } }
start()

// Reader thread: 100 ms chunks from stdin. Also ends a phrase after 1.4 s with no change in the transcript.
let reader = Thread {
    let bytesPerChunk = 3200
    var raw = [UInt8](repeating: 0, count: bytesPerChunk)
    while true {
        var got = 0
        while got < bytesPerChunk {
            let n = read(sock, &raw[got], bytesPerChunk - got)
            if n <= 0 { exit(0) }
            got += n
        }
        let data = Data(raw)
        let frames = AVAudioFrameCount(data.count / 2)
        guard let buf = AVAudioPCMBuffer(pcmFormat: fmt, frameCapacity: frames) else { continue }
        buf.frameLength = frames
        data.withUnsafeBytes { raw in
            if let base = raw.baseAddress { memcpy(buf.int16ChannelData![0], base, data.count) }
        }
        lock.lock()
        req.append(buf)
        let idle = Date().timeIntervalSince(lastChange)
        let pending = lastText
        lock.unlock()
        if !pending.isEmpty && idle > 1.4 {
            lock.lock(); lastText = ""; lock.unlock()
            emit(["t": "final", "text": pending])
            restart()          // a fresh session right away, so the next sentence is heard from its first word
        }
    }
}
reader.start()
RunLoop.main.run()
