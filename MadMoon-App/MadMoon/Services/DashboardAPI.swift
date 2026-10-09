import Foundation

actor DashboardAPI {
    static let shared = DashboardAPI()

    private let baseURL = "http://52.50.39.82:7777"
    private let credentials = Data("madmoon:kossinna".utf8).base64EncodedString()

    private func request(_ path: String, method: String = "GET", body: [String: Any]? = nil) async throws -> Data {
        guard let url = URL(string: "\(baseURL)\(path)") else { throw URLError(.badURL) }
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("Basic \(credentials)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = 10
        if let body = body {
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, _) = try await URLSession.shared.data(for: req)
        return data
    }

    func fetchOverview() async throws -> DashboardOverview {
        let data = try await request("/api/overview")
        return try JSONDecoder().decode(DashboardOverview.self, from: data)
    }

    func fetchProjects() async throws -> [DashboardProject] {
        let data = try await request("/api/projects")
        return try JSONDecoder().decode([DashboardProject].self, from: data)
    }

    func fetchProject(_ id: String) async throws -> DashboardProject {
        let data = try await request("/api/projects/\(id)")
        return try JSONDecoder().decode(DashboardProject.self, from: data)
    }

    func updateProject(_ id: String, updates: [String: Any]) async throws {
        _ = try await request("/api/projects/\(id)", method: "PUT", body: updates)
    }

    func addTask(_ projectId: String, title: String, priority: Int) async throws {
        _ = try await request("/api/projects/\(projectId)/tasks", method: "POST", body: ["title": title, "priority": priority])
    }

    func toggleTask(_ projectId: String, taskId: String, completed: Bool) async throws {
        _ = try await request("/api/projects/\(projectId)/tasks/\(taskId)", method: "PUT", body: ["completed": completed])
    }

    func addNote(_ projectId: String, text: String) async throws {
        _ = try await request("/api/projects/\(projectId)/notes", method: "POST", body: ["text": text])
    }

    func addTransaction(_ projectId: String, type: String, amount: Double, desc: String, category: String) async throws {
        _ = try await request("/api/projects/\(projectId)/transactions", method: "POST", body: ["type": type, "amount": amount, "desc": desc, "category": category])
    }

    func capture(text: String, project: String?, type: String, priority: String) async throws {
        var body: [String: Any] = ["text": text, "type": type, "priority": priority]
        if let p = project { body["project"] = p }
        _ = try await request("/api/capture", method: "POST", body: body)
    }

    func fetchCaptures() async throws -> [DashboardCapture] {
        let data = try await request("/api/captures")
        return try JSONDecoder().decode([DashboardCapture].self, from: data)
    }
}

// MARK: - API Models

struct DashboardOverview: Codable {
    let totalIncome: Double
    let totalExpenses: Double
    let netRevenue: Double
    let health: HealthCount
    let projectCount: Int
}

struct HealthCount: Codable {
    let green: Int
    let yellow: Int
    let red: Int
}

struct DashboardProject: Codable, Identifiable {
    let id: String
    let name: String
    let color: String
    var health: String
    var status: String
    var lastTouched: String?
    var kpis: [DKPI]
    var tasks: [DTask]
    var notes: [DNote]
    var transactions: [DTransaction]
}

struct DKPI: Codable {
    let label: String
    var value: String
}

struct DTask: Codable, Identifiable {
    let id: String
    let title: String
    let priority: Int
    var completed: Bool
    let created: String?
}

struct DNote: Codable, Identifiable {
    let id: String
    let text: String
    let created: String?
}

struct DTransaction: Codable, Identifiable {
    let id: String
    let type: String
    let amount: Double
    let category: String
    let desc: String
    let date: String
}

struct DashboardCapture: Codable, Identifiable {
    let id: String
    let text: String
    let project: String?
    let type: String
    let priority: String
    let created: String?
}
