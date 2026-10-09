import Foundation
import SwiftData

struct SeedData {
    static func seedIfNeeded(context: ModelContext) {
        let descriptor = FetchDescriptor<Project>()
        let count = (try? context.fetchCount(descriptor)) ?? 0
        if count > 0 { return }

        let projects = [
            Project(name: "UmmaGlobal", accentColor: "#1B5E3B", sortOrder: 0, statusLine: "Noor Build 8 in Apple review"),
            Project(name: "Bamba", accentColor: "#0F4C75", sortOrder: 1, statusLine: "Legal/land — slow progress"),
            Project(name: "OneBrain", accentColor: "#7C3AED", sortOrder: 2, statusLine: "Software ready, hardware Oct 25"),
            Project(name: "App Factory", accentColor: "#F59E0B", sortOrder: 3, statusLine: "Setting up Fiverr"),
            Project(name: "BizData", accentColor: "#14B8A6", sortOrder: 4, statusLine: "Planning phase"),
        ]

        for p in projects {
            context.insert(p)
        }

        // Streaks
        let streaks = [
            Streak(label: "Meditation"),
            Streak(label: "Gym"),
            Streak(label: "Deep Work"),
        ]
        for s in streaks {
            context.insert(s)
        }

        try? context.save()
    }
}
