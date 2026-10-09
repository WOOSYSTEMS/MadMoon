import Foundation
import SwiftData

// MARK: - Project

@Model
final class Project {
    var id: UUID
    var name: String
    var accentColor: String
    var health: String // "green", "yellow", "red"
    var statusLine: String
    var lastTouched: Date
    var sortOrder: Int

    @Relationship(deleteRule: .cascade) var kpis: [KPI]
    @Relationship(deleteRule: .cascade) var tasks: [ProjectTask]
    @Relationship(deleteRule: .cascade) var milestones: [Milestone]
    @Relationship(deleteRule: .cascade) var notes: [Note]
    @Relationship(deleteRule: .cascade) var transactions: [Transaction]

    init(name: String, accentColor: String, sortOrder: Int, statusLine: String = "") {
        self.id = UUID()
        self.name = name
        self.accentColor = accentColor
        self.health = "green"
        self.statusLine = statusLine
        self.lastTouched = Date()
        self.sortOrder = sortOrder
        self.kpis = []
        self.tasks = []
        self.milestones = []
        self.notes = []
        self.transactions = []
    }
}

// MARK: - KPI

@Model
final class KPI {
    var id: UUID
    var label: String
    var value: String
    var updatedAt: Date
    var project: Project?

    init(label: String, value: String, project: Project? = nil) {
        self.id = UUID()
        self.label = label
        self.value = value
        self.updatedAt = Date()
        self.project = project
    }
}

// MARK: - Task

@Model
final class ProjectTask {
    var id: UUID
    var title: String
    var priority: Int // 1=P1, 2=P2, 3=P3
    var dueDate: Date?
    var completed: Bool
    var createdAt: Date
    var project: Project?

    init(title: String, priority: Int = 2, dueDate: Date? = nil, project: Project? = nil) { // ProjectTask
        self.id = UUID()
        self.title = title
        self.priority = priority
        self.dueDate = dueDate
        self.completed = false
        self.createdAt = Date()
        self.project = project
    }
}

// MARK: - Milestone

@Model
final class Milestone {
    var id: UUID
    var title: String
    var targetDate: Date
    var progress: Double
    var project: Project?

    init(title: String, targetDate: Date, progress: Double = 0, project: Project? = nil) {
        self.id = UUID()
        self.title = title
        self.targetDate = targetDate
        self.progress = progress
        self.project = project
    }
}

// MARK: - Note

@Model
final class Note {
    var id: UUID
    var body: String
    var createdAt: Date
    var project: Project?

    init(body: String, project: Project? = nil) {
        self.id = UUID()
        self.body = body
        self.createdAt = Date()
        self.project = project
    }
}

// MARK: - Transaction

@Model
final class Transaction {
    var id: UUID
    var type: String // "income" or "expense"
    var amount: Double
    var category: String
    var date: Date
    var desc: String
    var project: Project?

    init(type: String, amount: Double, category: String = "", desc: String = "", project: Project? = nil) {
        self.id = UUID()
        self.type = type
        self.amount = amount
        self.category = category
        self.date = Date()
        self.desc = desc
        self.project = project
    }
}

// MARK: - TimeBlock

@Model
final class TimeBlock {
    var id: UUID
    var date: Date
    var hour: Int
    var projectId: UUID?
    var signal: String? // "productive", "noise", "break"

    init(date: Date, hour: Int, projectId: UUID? = nil) {
        self.id = UUID()
        self.date = date
        self.hour = hour
        self.projectId = projectId
    }
}

// MARK: - Capture

@Model
final class Capture {
    var id: UUID
    var projectId: UUID?
    var type: String // "idea", "task", "note"
    var text: String
    var priority: Int
    var createdAt: Date

    init(text: String, type: String = "idea", priority: Int = 2, projectId: UUID? = nil) {
        self.id = UUID()
        self.text = text
        self.type = type
        self.priority = priority
        self.projectId = projectId
        self.createdAt = Date()
    }
}

// MARK: - Streak

@Model
final class Streak {
    var id: UUID
    var label: String
    var currentCount: Int
    var lastLogDate: Date?

    init(label: String) {
        self.id = UUID()
        self.label = label
        self.currentCount = 0
    }

    func logToday() {
        let cal = Calendar.current
        if let last = lastLogDate, cal.isDateInToday(last) { return }
        if let last = lastLogDate, cal.isDateInYesterday(last) {
            currentCount += 1
        } else {
            currentCount = 1
        }
        lastLogDate = Date()
    }
}
