import SwiftUI
import SwiftData

@main
struct MadMoonApp: App {
    var body: some Scene {
        WindowGroup {
            LiveCommandView()
                .preferredColorScheme(.dark)
        }
        .modelContainer(for: [
            Project.self,
            KPI.self,
            ProjectTask.self,
            Milestone.self,
            Note.self,
            Transaction.self,
            TimeBlock.self,
            Capture.self,
            Streak.self,
        ])
    }
}
