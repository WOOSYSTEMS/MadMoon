import SwiftUI

@MainActor @Observable
class LiveDashboardVM {
    var overview: DashboardOverview?
    var projects: [DashboardProject] = []
    var captures: [DashboardCapture] = []
    var isLoading = true
    var error: String?

    func load() async {
        isLoading = true
        error = nil
        do {
            async let o = DashboardAPI.shared.fetchOverview()
            async let p = DashboardAPI.shared.fetchProjects()
            async let c = DashboardAPI.shared.fetchCaptures()
            overview = try await o
            projects = try await p
            captures = try await c
        } catch {
            self.error = "Offline — cannot reach Dublin"
        }
        isLoading = false
    }

    func toggleTask(_ projectId: String, taskId: String, completed: Bool) async {
        try? await DashboardAPI.shared.toggleTask(projectId, taskId: taskId, completed: completed)
        await load()
    }

    func addTask(_ projectId: String, title: String, priority: Int) async {
        try? await DashboardAPI.shared.addTask(projectId, title: title, priority: priority)
        await load()
    }

    func addNote(_ projectId: String, text: String) async {
        try? await DashboardAPI.shared.addNote(projectId, text: text)
        await load()
    }

    func updateHealth(_ projectId: String, health: String) async {
        try? await DashboardAPI.shared.updateProject(projectId, updates: ["health": health])
        await load()
    }

    func updateStatus(_ projectId: String, status: String) async {
        try? await DashboardAPI.shared.updateProject(projectId, updates: ["status": status])
        await load()
    }

    func capture(text: String, project: String?, type: String, priority: String) async {
        try? await DashboardAPI.shared.capture(text: text, project: project, type: type, priority: priority)
        await load()
    }
}

struct LiveCommandView: View {
    @State private var vm = LiveDashboardVM()
    @State private var selectedProject: DashboardProject?
    @State private var showCapture = false
    @State private var showTerminal = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()

                if vm.isLoading && vm.projects.isEmpty {
                    ProgressView().tint(.white)
                } else if let err = vm.error, vm.projects.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "wifi.slash")
                            .font(.largeTitle)
                            .foregroundStyle(.red)
                        Text(err)
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(Color(hex: "#71717A"))
                        Button("Retry") { Task { await vm.load() } }
                            .foregroundStyle(.white)
                    }
                } else {
                    ScrollView {
                        VStack(spacing: 16) {
                            statsBar
                            projectList
                            capturesList
                            Spacer(minLength: 80)
                        }
                        .padding(.horizontal, 14)
                    }
                    .refreshable { await vm.load() }
                }

                // FAB
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Button { showCapture = true } label: {
                            Image(systemName: "plus")
                                .font(.system(size: 22, weight: .bold))
                                .foregroundStyle(.white)
                                .frame(width: 56, height: 56)
                                .background(Circle().fill(LinearGradient(colors: [Color(hex: "#7C3AED"), Color(hex: "#F59E0B")], startPoint: .topLeading, endPoint: .bottomTrailing)))
                                .shadow(color: Color(hex: "#7C3AED").opacity(0.4), radius: 12, y: 4)
                        }
                        .padding(.trailing, 16)
                        .padding(.bottom, 16)
                    }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 8) {
                        Image(systemName: "moon.fill")
                            .font(.system(size: 16, weight: .bold))
                            .foregroundStyle(.white)
                        Text("MADMOON")
                            .font(.system(size: 16, weight: .black, design: .monospaced))
                            .foregroundStyle(.white)
                            .tracking(3)
                    }
                }
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        if let url = URL(string: "http://52.50.39.82:9999") {
                            UIApplication.shared.open(url)
                        }
                    } label: {
                        Image(systemName: "terminal.fill")
                            .foregroundStyle(Color(hex: "#7C3AED"))
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await vm.load() } } label: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(Color(hex: "#71717A"))
                    }
                }
            }
            .sheet(item: $selectedProject) { project in
                LiveProjectDetailView(vm: vm, project: project)
            }
            .sheet(isPresented: $showCapture) {
                LiveCaptureView(vm: vm, projects: vm.projects)
            }
            .fullScreenCover(isPresented: $showTerminal) {
                TerminalView()
            }
            .task { await vm.load() }
        }
    }

    // MARK: - Stats Bar

    private var statsBar: some View {
        HStack(spacing: 0) {
            if let o = vm.overview {
                statCell("PROJECTS", "\(o.projectCount)")
                statCell("INCOME", "$\(Int(o.totalIncome))", color: .green)
                statCell("EXPENSES", "$\(Int(o.totalExpenses))", color: .red)
                statCell("NET", "\(o.netRevenue >= 0 ? "+" : "-")$\(Int(abs(o.netRevenue)))", color: o.netRevenue >= 0 ? .green : .red)
            }
        }
        .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))
    }

    private func statCell(_ label: String, _ value: String, color: Color = .white) -> some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.system(size: 8, weight: .semibold, design: .monospaced))
                .foregroundStyle(Color(hex: "#71717A"))
                .tracking(1)
            Text(value)
                .font(.system(size: 14, weight: .bold, design: .monospaced))
                .foregroundStyle(color)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 10)
    }

    // MARK: - Projects

    private var projectList: some View {
        VStack(spacing: 10) {
            ForEach(vm.projects) { p in
                Button { selectedProject = p } label: {
                    LiveProjectCard(project: p)
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Captures

    private var capturesList: some View {
        VStack(alignment: .leading, spacing: 8) {
            if !vm.captures.isEmpty {
                Text("RECENT CAPTURES")
                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                    .foregroundStyle(Color(hex: "#71717A"))
                    .tracking(2)
                    .padding(.top, 8)

                ForEach(vm.captures.prefix(5)) { c in
                    HStack {
                        Text(c.text)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(.white)
                            .lineLimit(2)
                        Spacer()
                        if let proj = vm.projects.first(where: { $0.id == c.project }) {
                            Text(proj.name)
                                .font(.system(size: 10, design: .monospaced))
                                .foregroundStyle(Color(hex: proj.color))
                        }
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))
                }
            }
        }
    }
}

// MARK: - Project Card

struct LiveProjectCard: View {
    let project: DashboardProject

    var body: some View {
        HStack(spacing: 12) {
            RoundedRectangle(cornerRadius: 2)
                .fill(Color(hex: project.color))
                .frame(width: 4)

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(project.name)
                        .font(.system(.subheadline, design: .rounded, weight: .bold))
                        .foregroundStyle(.white)
                    Spacer()
                    let openTasks = project.tasks.filter { !$0.completed }.count
                    if openTasks > 0 {
                        Text("\(openTasks)")
                            .font(.system(size: 11, weight: .bold, design: .monospaced))
                            .foregroundStyle(.yellow)
                    }
                    Circle()
                        .fill(project.health == "green" ? .green : project.health == "yellow" ? .yellow : .red)
                        .frame(width: 8, height: 8)
                }

                Text(project.status)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(Color(hex: "#71717A"))
                    .lineLimit(1)

                // KPIs grid
                LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 4) {
                    ForEach(project.kpis, id: \.label) { kpi in
                        HStack {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(kpi.label)
                                    .font(.system(size: 8, design: .monospaced))
                                    .foregroundStyle(Color(hex: "#71717A"))
                                Text(kpi.value)
                                    .font(.system(size: 11, weight: .bold, design: .monospaced))
                                    .foregroundStyle(Color(hex: project.color))
                            }
                            Spacer()
                        }
                        .padding(5)
                        .background(RoundedRectangle(cornerRadius: 4).fill(Color(hex: "#0A0A0F")))
                    }
                }
            }
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(hex: "#14141F")).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color(hex: "#1E1E2E"), lineWidth: 0.5)))
    }
}

// MARK: - Project Detail

struct LiveProjectDetailView: View {
    let vm: LiveDashboardVM
    let project: DashboardProject
    @Environment(\.dismiss) private var dismiss
    @State private var newTask = ""
    @State private var newNote = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        // Health
                        HStack(spacing: 8) {
                            ForEach(["green", "yellow", "red"], id: \.self) { h in
                                Button { Task { await vm.updateHealth(project.id, health: h) }; dismiss() } label: {
                                    Circle().fill(h == "green" ? .green : h == "yellow" ? .yellow : .red)
                                        .frame(width: 28, height: 28)
                                        .opacity(project.health == h ? 1 : 0.25)
                                }
                            }
                            Spacer()
                        }

                        // Status
                        Text(project.status)
                            .font(.system(.body, design: .monospaced))
                            .foregroundStyle(.white)
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))

                        // KPIs
                        sectionLabel("KPIs")
                        LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 6) {
                            ForEach(project.kpis, id: \.label) { kpi in
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(kpi.label).font(.system(size: 9, design: .monospaced)).foregroundStyle(Color(hex: "#71717A"))
                                    Text(kpi.value).font(.system(size: 14, weight: .bold, design: .monospaced)).foregroundStyle(Color(hex: project.color))
                                }
                                .padding(8)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))
                            }
                        }

                        // Tasks
                        let open = project.tasks.filter { !$0.completed }
                        let done = project.tasks.filter { $0.completed }
                        sectionLabel("TASKS — \(open.count) open · \(done.count) done")

                        ForEach(project.tasks.sorted { ($0.completed ? 1:0, $0.priority) < ($1.completed ? 1:0, $1.priority) }) { t in
                            HStack(spacing: 8) {
                                Button { Task { await vm.toggleTask(project.id, taskId: t.id, completed: !t.completed) }; dismiss() } label: {
                                    Image(systemName: t.completed ? "checkmark.circle.fill" : "circle")
                                        .foregroundStyle(t.completed ? .green : Color(hex: "#71717A"))
                                }
                                Text(t.title)
                                    .font(.system(size: 13, design: .monospaced))
                                    .foregroundStyle(t.completed ? Color(hex: "#71717A") : .white)
                                    .strikethrough(t.completed)
                                Spacer()
                                Text("P\(t.priority)")
                                    .font(.system(size: 10, weight: .bold, design: .monospaced))
                                    .foregroundStyle(t.priority == 1 ? .red : t.priority == 2 ? .yellow : Color(hex: "#71717A"))
                            }
                        }

                        HStack {
                            TextField("New task...", text: $newTask)
                                .font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(.white)
                                .onSubmit { addTask() }
                            Button("+") { addTask() }
                                .foregroundStyle(Color(hex: project.color))
                                .disabled(newTask.isEmpty)
                        }
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))

                        // Notes
                        sectionLabel("LOG — \(project.notes.count) entries")
                        ForEach(project.notes.prefix(10)) { n in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(n.text).font(.system(size: 12, design: .monospaced)).foregroundStyle(.white)
                                Text(n.created ?? "").font(.system(size: 10, design: .monospaced)).foregroundStyle(Color(hex: "#71717A"))
                            }.padding(.vertical, 4)
                        }

                        HStack {
                            TextField("Add note...", text: $newNote)
                                .font(.system(size: 13, design: .monospaced))
                                .foregroundStyle(.white)
                                .onSubmit { addNote() }
                            Button("+") { addNote() }
                                .foregroundStyle(Color(hex: project.color))
                                .disabled(newNote.isEmpty)
                        }
                        .padding(8)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))

                        // Financials
                        let inc = project.transactions.filter { $0.type == "income" }.reduce(0.0) { $0 + $1.amount }
                        let exp = project.transactions.filter { $0.type == "expense" }.reduce(0.0) { $0 + $1.amount }
                        sectionLabel("FINANCIALS")
                        HStack(spacing: 16) {
                            VStack { Text("Income").font(.system(size: 9, design: .monospaced)).foregroundStyle(Color(hex: "#71717A")); Text("+$\(Int(inc))").font(.system(size: 16, weight: .bold, design: .monospaced)).foregroundStyle(.green) }
                            VStack { Text("Expenses").font(.system(size: 9, design: .monospaced)).foregroundStyle(Color(hex: "#71717A")); Text("-$\(Int(exp))").font(.system(size: 16, weight: .bold, design: .monospaced)).foregroundStyle(.red) }
                            VStack { Text("Net").font(.system(size: 9, design: .monospaced)).foregroundStyle(Color(hex: "#71717A")); Text("$\(Int(inc - exp))").font(.system(size: 16, weight: .bold, design: .monospaced)).foregroundStyle(inc - exp >= 0 ? .green : .red) }
                        }
                        .padding(10)
                        .frame(maxWidth: .infinity)
                        .background(RoundedRectangle(cornerRadius: 6).fill(Color(hex: "#14141F")))

                        Spacer(minLength: 40)
                    }
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 6) {
                        Circle().fill(Color(hex: project.color)).frame(width: 8, height: 8)
                        Text(project.name).font(.system(.headline, design: .rounded, weight: .bold)).foregroundStyle(.white)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }.foregroundStyle(Color(hex: project.color))
                }
            }
        }
    }

    private func sectionLabel(_ text: String) -> some View {
        Text(text)
            .font(.system(size: 10, weight: .bold, design: .monospaced))
            .foregroundStyle(Color(hex: "#71717A"))
            .tracking(1.5)
            .padding(.top, 4)
    }

    private func addTask() {
        guard !newTask.isEmpty else { return }
        Task { await vm.addTask(project.id, title: newTask, priority: 2) }
        newTask = ""
        dismiss()
    }

    private func addNote() {
        guard !newNote.isEmpty else { return }
        Task { await vm.addNote(project.id, text: newNote) }
        newNote = ""
        dismiss()
    }
}

// MARK: - Capture View

struct LiveCaptureView: View {
    let vm: LiveDashboardVM
    let projects: [DashboardProject]
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var selectedProjectId: String?
    @State private var captureType = "idea"
    @State private var priority = "P2"

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()
                VStack(spacing: 16) {
                    TextField("Capture something...", text: $text, axis: .vertical)
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(.white)
                        .lineLimit(3...6)
                        .padding(12)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))
                        .padding(.top, 12)

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 6) {
                            ForEach(projects) { p in
                                Button { selectedProjectId = p.id } label: {
                                    Text(p.name)
                                        .font(.system(size: 12, weight: .semibold, design: .rounded))
                                        .foregroundStyle(selectedProjectId == p.id ? .white : Color(hex: "#71717A"))
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 6)
                                        .background(Capsule().fill(selectedProjectId == p.id ? Color(hex: p.color) : Color(hex: "#14141F")))
                                }
                            }
                        }
                    }

                    HStack(spacing: 6) {
                        ForEach(["idea", "task", "note"], id: \.self) { t in
                            Button { captureType = t } label: {
                                Text(t).font(.system(size: 12, weight: .semibold, design: .monospaced))
                                    .foregroundStyle(captureType == t ? .white : Color(hex: "#71717A"))
                                    .padding(.horizontal, 12).padding(.vertical, 6)
                                    .background(Capsule().fill(captureType == t ? Color(hex: "#7C3AED") : Color(hex: "#14141F")))
                            }
                        }
                        Spacer()
                    }

                    Spacer()
                }
                .padding(.horizontal, 14)
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { Button("Cancel") { dismiss() }.foregroundStyle(Color(hex: "#71717A")) }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Save") {
                        Task { await vm.capture(text: text, project: selectedProjectId, type: captureType, priority: priority) }
                        dismiss()
                    }
                    .foregroundStyle(text.isEmpty ? Color(hex: "#71717A") : Color(hex: "#7C3AED"))
                    .disabled(text.isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }
}
