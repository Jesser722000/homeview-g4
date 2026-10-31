// HomeView calendar helper: reads the Mac's Calendar (every account the Calendar app has: iCloud, Google, Exchange...)
// and writes the next 7 days as JSON for the dashboard every 2 minutes. macOS asks once for permission.
import Foundation
import EventKit

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1]
          : NSHomeDirectory() + "/Library/Application Support/HomeView/data/calendar.json"
let store = EKEventStore()
let sem = DispatchSemaphore(value: 0)
var granted = false
if #available(macOS 14.0, *) {
    store.requestFullAccessToEvents { ok, _ in granted = ok; sem.signal() }
} else {
    store.requestAccess(to: .event) { ok, _ in granted = ok; sem.signal() }
}
sem.wait()

func write(_ obj: [String: Any]) {
    guard let d = try? JSONSerialization.data(withJSONObject: obj, options: [.sortedKeys]) else { return }
    let tmp = out + ".tmp"
    FileManager.default.createFile(atPath: tmp, contents: d)
    _ = try? FileManager.default.replaceItemAt(URL(fileURLWithPath: out), withItemAt: URL(fileURLWithPath: tmp))
    if !FileManager.default.fileExists(atPath: out) { try? FileManager.default.moveItem(atPath: tmp, toPath: out) }
}

let iso = ISO8601DateFormatter(); iso.formatOptions = [.withInternetDateTime]
while true {
    if !granted {
        write(["ok": false, "error": "calendar access not granted", "updated": iso.string(from: Date())])
        sleep(120); continue
    }
    store.refreshSourcesIfNecessary()
    let cal = Calendar.current
    let start = cal.startOfDay(for: Date())
    let end = cal.date(byAdding: .day, value: 7, to: start)!
    let calendars = store.calendars(for: .event)
    let events = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: calendars))
        .sorted { $0.startDate < $1.startDate }
    let list: [[String: Any]] = events.prefix(60).map { e in
        ["title": e.title ?? "Event", "start": iso.string(from: e.startDate), "end": iso.string(from: e.endDate),
         "all_day": e.isAllDay, "calendar": e.calendar?.title ?? "", "location": e.location ?? ""]
    }
    write(["ok": true, "updated": iso.string(from: Date()), "calendars": calendars.map { $0.title }, "events": list])
    sleep(120)
}
