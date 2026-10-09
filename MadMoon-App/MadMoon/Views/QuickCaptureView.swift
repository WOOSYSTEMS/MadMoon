import SwiftUI
import SwiftData

struct QuickCaptureView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @Query(sort: \Project.sortOrder) private var projects: [Project]

    @State private var text = ""
    @State private var selectedProjectId: UUID?
    @State private var captureType = "idea"
    @State private var priority = 2

    let types = ["idea", "task", "note"]

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()

                VStack(spacing: 20) {
                    // Text input
                    TextField("Capture something...", text: $text, axis: .vertical)
                        .font(.system(.body, design: .monospaced))
                        .foregroundStyle(.white)
                        .lineLimit(3...6)
                        .padding(14)
                        .background(
                            RoundedRectangle(cornerRadius: 10)
                                .fill(Color(hex: "#14141F"))
                        )
                        .padding(.top, 12)

                    // Project selector
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(projects) { project in
                                Button {
                                    selectedProjectId = project.id
                                } label: {
                                    Text(project.name)
                                        .font(.system(.caption, design: .rounded, weight: .semibold))
                                        .foregroundStyle(selectedProjectId == project.id ? .white : Color(hex: "#71717A"))
                                        .padding(.horizontal, 14)
                                        .padding(.vertical, 8)
                                        .background(
                                            Capsule()
                                                .fill(selectedProjectId == project.id
                                                      ? Color(hex: project.accentColor)
                                                      : Color(hex: "#14141F"))
                                        )
                                }
                            }
                        }
                    }

                    // Type selector
                    HStack(spacing: 8) {
                        ForEach(types, id: \.self) { t in
                            Button {
                                captureType = t
                            } label: {
                                HStack(spacing: 4) {
                                    Image(systemName: t == "idea" ? "lightbulb" : t == "task" ? "checkmark.circle" : "note.text")
                                        .font(.caption)
                                    Text(t.capitalized)
                                        .font(.system(.caption, design: .monospaced, weight: .semibold))
                                }
                                .foregroundStyle(captureType == t ? .white : Color(hex: "#71717A"))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 8)
                                .background(
                                    Capsule()
                                        .fill(captureType == t ? Color(hex: "#7C3AED") : Color(hex: "#14141F"))
                                )
                            }
                        }
                        Spacer()
                    }

                    // Priority
                    HStack(spacing: 8) {
                        ForEach(1...3, id: \.self) { p in
                            Button {
                                priority = p
                            } label: {
                                Text("P\(p)")
                                    .font(.system(.caption, design: .monospaced, weight: .bold))
                                    .foregroundStyle(priority == p ? .white : Color(hex: "#71717A"))
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 8)
                                    .background(
                                        Capsule()
                                            .fill(priority == p
                                                  ? (p == 1 ? Color.red : p == 2 ? Color.yellow : Color.gray).opacity(0.7)
                                                  : Color(hex: "#14141F"))
                                    )
                            }
                        }
                        Spacer()
                    }

                    Spacer()
                }
                .padding(.horizontal, 16)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(Color(hex: "#71717A"))
                }
                ToolbarItem(placement: .principal) {
                    Text("CAPTURE")
                        .font(.system(.caption, design: .monospaced, weight: .bold))
                        .foregroundStyle(.white)
                        .tracking(2)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        save()
                    } label: {
                        Text("Save")
                            .font(.system(.subheadline, design: .rounded, weight: .bold))
                            .foregroundStyle(text.isEmpty ? Color(hex: "#71717A") : Color(hex: "#7C3AED"))
                    }
                    .disabled(text.isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }

    private func save() {
        let capture = Capture(text: text, type: captureType, priority: priority, projectId: selectedProjectId)
        context.insert(capture)

        // If it's a task, also add to the project's task list
        if captureType == "task", let pid = selectedProjectId,
           let project = projects.first(where: { $0.id == pid }) {
            let task = ProjectTask(title: text, priority: priority, project: project)
            context.insert(task)
            project.tasks.append(task)
            project.lastTouched = Date()
        }

        dismiss()
    }
}
