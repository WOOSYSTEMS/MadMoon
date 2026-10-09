import SwiftUI
import SwiftData

struct ProjectDetailView: View {
    @Bindable var project: Project
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @State private var newTaskTitle = ""
    @State private var newNote = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 20) {
                        // Health toggle
                        healthSection

                        // Status line
                        statusSection

                        // KPIs
                        if !project.kpis.isEmpty {
                            kpiSection
                        }

                        // Tasks
                        taskSection

                        // Milestones
                        if !project.milestones.isEmpty {
                            milestoneSection
                        }

                        // Notes
                        noteSection

                        // Financials
                        financialSection

                        Spacer(minLength: 40)
                    }
                    .padding(.horizontal, 16)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(Color(hex: project.accentColor))
                            .frame(width: 10, height: 10)
                        Text(project.name)
                            .font(.system(.headline, design: .rounded, weight: .bold))
                            .foregroundStyle(.white)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(Color(hex: project.accentColor))
                }
            }
        }
        .presentationDetents([.large])
    }

    // MARK: - Health

    private var healthSection: some View {
        HStack(spacing: 12) {
            ForEach(["green", "yellow", "red"], id: \.self) { h in
                Button {
                    project.health = h
                    project.lastTouched = Date()
                } label: {
                    Circle()
                        .fill(h == "green" ? .green : h == "yellow" ? .yellow : .red)
                        .frame(width: 28, height: 28)
                        .opacity(project.health == h ? 1.0 : 0.25)
                        .overlay(
                            Circle()
                                .stroke(.white.opacity(project.health == h ? 0.5 : 0), lineWidth: 2)
                        )
                }
            }
            Spacer()
        }
        .padding(.top, 12)
    }

    // MARK: - Status

    private var statusSection: some View {
        TextField("Status...", text: $project.statusLine)
            .font(.system(.body, design: .monospaced))
            .foregroundStyle(.white)
            .padding(12)
            .background(
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(hex: "#14141F"))
            )
    }

    // MARK: - KPIs

    private var kpiSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("KPIs")
            LazyVGrid(columns: [.init(.flexible()), .init(.flexible())], spacing: 10) {
                ForEach(project.kpis) { kpi in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(kpi.label)
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(Color(hex: "#71717A"))
                        Text(kpi.value)
                            .font(.system(.title3, design: .monospaced, weight: .bold))
                            .foregroundStyle(Color(hex: project.accentColor))
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(12)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))
                }
            }
        }
    }

    // MARK: - Tasks

    private var taskSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Tasks")

            // Add task
            HStack {
                TextField("New task...", text: $newTaskTitle)
                    .font(.system(.subheadline, design: .monospaced))
                    .foregroundStyle(.white)
                    .onSubmit { addTask() }

                Button { addTask() } label: {
                    Image(systemName: "plus.circle.fill")
                        .foregroundStyle(Color(hex: project.accentColor))
                }
                .disabled(newTaskTitle.isEmpty)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))

            // Task list
            ForEach(project.tasks.sorted { ($0.completed ? 1 : 0, $0.priority) < ($1.completed ? 1 : 0, $1.priority) }) { task in
                HStack(spacing: 10) {
                    Button {
                        task.completed.toggle()
                        project.lastTouched = Date()
                    } label: {
                        Image(systemName: task.completed ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(task.completed ? .green : Color(hex: "#71717A"))
                    }

                    Text(task.title)
                        .font(.system(.subheadline, design: .monospaced))
                        .foregroundStyle(task.completed ? Color(hex: "#71717A") : .white)
                        .strikethrough(task.completed)

                    Spacer()

                    Text("P\(task.priority)")
                        .font(.system(.caption2, design: .monospaced, weight: .bold))
                        .foregroundStyle(task.priority == 1 ? .red : task.priority == 2 ? .yellow : Color(hex: "#71717A"))
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
            }
        }
    }

    private func addTask() {
        guard !newTaskTitle.isEmpty else { return }
        let task = ProjectTask(title: newTaskTitle, project: project)
        context.insert(task)
        project.tasks.append(task)
        project.lastTouched = Date()
        newTaskTitle = ""
    }

    // MARK: - Milestones

    private var milestoneSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Milestones")
            ForEach(project.milestones) { ms in
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(ms.title)
                            .font(.system(.subheadline, design: .monospaced, weight: .semibold))
                            .foregroundStyle(.white)
                        Spacer()
                        Text("\(Int(ms.progress * 100))%")
                            .font(.system(.caption, design: .monospaced))
                            .foregroundStyle(Color(hex: project.accentColor))
                    }
                    ProgressView(value: ms.progress)
                        .tint(Color(hex: project.accentColor))
                }
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))
            }
        }
    }

    // MARK: - Notes

    private var noteSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Log")

            HStack {
                TextField("Add note...", text: $newNote)
                    .font(.system(.subheadline, design: .monospaced))
                    .foregroundStyle(.white)
                    .onSubmit { addNote() }

                Button { addNote() } label: {
                    Image(systemName: "arrow.up.circle.fill")
                        .foregroundStyle(Color(hex: project.accentColor))
                }
                .disabled(newNote.isEmpty)
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))

            ForEach(project.notes.sorted { $0.createdAt > $1.createdAt }.prefix(10), id: \.id) { note in
                VStack(alignment: .leading, spacing: 4) {
                    Text(note.body)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(.white)
                    Text(note.createdAt, format: .relative(presentation: .named))
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                }
                .padding(8)
            }
        }
    }

    private func addNote() {
        guard !newNote.isEmpty else { return }
        let note = Note(body: newNote, project: project)
        context.insert(note)
        project.notes.append(note)
        project.lastTouched = Date()
        newNote = ""
    }

    // MARK: - Financials

    private var financialSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("Financials")
            HStack(spacing: 20) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Income")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                    Text("$\(income, specifier: "%.0f")")
                        .font(.system(.title3, design: .monospaced, weight: .bold))
                        .foregroundStyle(.green)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Expenses")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                    Text("$\(expenses, specifier: "%.0f")")
                        .font(.system(.title3, design: .monospaced, weight: .bold))
                        .foregroundStyle(.red)
                }
                VStack(alignment: .leading, spacing: 4) {
                    Text("Net")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                    Text("$\(income - expenses, specifier: "%.0f")")
                        .font(.system(.title3, design: .monospaced, weight: .bold))
                        .foregroundStyle(income - expenses >= 0 ? .green : .red)
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color(hex: "#14141F")))
        }
    }

    private var income: Double {
        project.transactions.filter { $0.type == "income" }.reduce(0) { $0 + $1.amount }
    }
    private var expenses: Double {
        project.transactions.filter { $0.type == "expense" }.reduce(0) { $0 + $1.amount }
    }

    // MARK: - Helpers

    private func sectionHeader(_ title: String) -> some View {
        Text(title.uppercased())
            .font(.system(.caption, design: .monospaced, weight: .bold))
            .foregroundStyle(Color(hex: "#71717A"))
            .tracking(2)
            .padding(.top, 8)
    }
}
