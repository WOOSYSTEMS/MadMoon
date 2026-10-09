import SwiftUI
import SwiftData

struct CommandCenterView: View {
    @Environment(\.modelContext) private var context
    @Query(sort: \Project.sortOrder) private var projects: [Project]
    @State private var showCapture = false
    @State private var selectedProject: Project?

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 20) {
                        headerSection
                        projectCards
                        Spacer(minLength: 80)
                    }
                    .padding(.horizontal, 16)
                }

                // Quick Capture FAB
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        Button {
                            showCapture = true
                        } label: {
                            Image(systemName: "plus")
                                .font(.system(size: 22, weight: .bold))
                                .foregroundStyle(.white)
                                .frame(width: 56, height: 56)
                                .background(
                                    Circle()
                                        .fill(
                                            LinearGradient(
                                                colors: [Color(hex: "#7C3AED"), Color(hex: "#F59E0B")],
                                                startPoint: .topLeading,
                                                endPoint: .bottomTrailing
                                            )
                                        )
                                )
                                .shadow(color: Color(hex: "#7C3AED").opacity(0.4), radius: 12, y: 4)
                        }
                        .padding(.trailing, 20)
                        .padding(.bottom, 20)
                    }
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 8) {
                        Image(systemName: "moon.fill")
                            .font(.system(size: 18, weight: .bold))
                            .foregroundStyle(.white)
                        Text("MADMOON")
                            .font(.system(size: 18, weight: .black, design: .monospaced))
                            .foregroundStyle(.white)
                            .tracking(3)
                    }
                }
            }
            .sheet(isPresented: $showCapture) {
                QuickCaptureView()
            }
            .sheet(item: $selectedProject) { project in
                ProjectDetailView(project: project)
            }
            .onAppear {
                SeedData.seedIfNeeded(context: context)
            }
        }
    }

    // MARK: - Header

    private var headerSection: some View {
        VStack(spacing: 8) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(Date(), format: .dateTime.weekday(.wide).month().day())
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))

                    Text("$\(totalRevenue, specifier: "%.0f")")
                        .font(.system(size: 32, weight: .bold, design: .monospaced))
                        .foregroundStyle(.white)

                    Text("Portfolio Revenue (30d)")
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                }
                Spacer()
            }
        }
        .padding(.top, 12)
    }

    private var totalRevenue: Double {
        projects.flatMap(\.transactions)
            .filter { $0.type == "income" && $0.date > Date().addingTimeInterval(-30*24*3600) }
            .reduce(0) { $0 + $1.amount }
    }

    // MARK: - Project Cards

    private var projectCards: some View {
        VStack(spacing: 12) {
            ForEach(projects) { project in
                Button {
                    selectedProject = project
                } label: {
                    ProjectCardView(project: project)
                }
                .buttonStyle(.plain)
            }
        }
    }
}

// MARK: - Project Card

struct ProjectCardView: View {
    let project: Project

    var body: some View {
        HStack(spacing: 14) {
            // Accent bar
            RoundedRectangle(cornerRadius: 2)
                .fill(Color(hex: project.accentColor))
                .frame(width: 4)

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(project.name)
                        .font(.system(.subheadline, design: .rounded, weight: .bold))
                        .foregroundStyle(.white)

                    Spacer()

                    // Health dot
                    Circle()
                        .fill(healthColor)
                        .frame(width: 8, height: 8)

                    // Top KPI
                    if let kpi = project.kpis.first {
                        Text(kpi.value)
                            .font(.system(.caption, design: .monospaced, weight: .semibold))
                            .foregroundStyle(Color(hex: project.accentColor))
                    }
                }

                if !project.statusLine.isEmpty {
                    Text(project.statusLine)
                        .font(.system(.caption, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                        .lineLimit(1)
                }

                HStack {
                    let pendingTasks = project.tasks.filter { !$0.completed }.count
                    if pendingTasks > 0 {
                        Label("\(pendingTasks)", systemImage: "checkmark.circle")
                            .font(.system(.caption2, design: .monospaced))
                            .foregroundStyle(Color(hex: "#71717A"))
                    }

                    Spacer()

                    Text(project.lastTouched, format: .relative(presentation: .named))
                        .font(.system(.caption2, design: .monospaced))
                        .foregroundStyle(Color(hex: "#71717A"))
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 14)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color(hex: "#14141F"))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color(hex: "#1E1E2E"), lineWidth: 0.5)
                )
        )
    }

    private var healthColor: Color {
        switch project.health {
        case "green": .green
        case "yellow": .yellow
        case "red": .red
        default: .gray
        }
    }
}

// MARK: - Color Extension

extension Color {
    init(hex: String) {
        let hex = hex.trimmingCharacters(in: CharacterSet(charactersIn: "#"))
        let scanner = Scanner(string: hex)
        var rgb: UInt64 = 0
        scanner.scanHexInt64(&rgb)
        let r = Double((rgb >> 16) & 0xFF) / 255.0
        let g = Double((rgb >> 8) & 0xFF) / 255.0
        let b = Double(rgb & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b)
    }
}
