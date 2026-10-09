import SwiftUI

@main
struct FitnessApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                DashboardView().tabItem { Label("Dashboard", systemImage: "heart.fill") }
                WorkoutsView().tabItem { Label("Workouts", systemImage: "figure.run") }
                ProgressView_().tabItem { Label("Progress", systemImage: "chart.line.uptrend.xyaxis") }
                Text("Profile").tabItem { Label("Profile", systemImage: "person.fill") }
            }
            .tint(Color(red: 0, green: 0.96, blue: 0.63))
            .preferredColorScheme(.dark)
        }
    }
}

let bg = Color(red: 0.1, green: 0.1, blue: 0.18)
let surface = Color(red: 0.086, green: 0.13, blue: 0.24)
let accent = Color(red: 0, green: 0.96, blue: 0.63)

// MARK: - Dashboard

struct DashboardView: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Stats rings
                    HStack(spacing: 20) {
                        StatRing(label: "Steps", value: "8,432", total: "10,000", progress: 0.84, color: accent)
                        StatRing(label: "Calories", value: "524", total: "700", progress: 0.75, color: .orange)
                        StatRing(label: "Minutes", value: "45", total: "60", progress: 0.75, color: .cyan)
                    }
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 16).fill(surface))
                    .padding(.horizontal)

                    // Weekly chart
                    VStack(alignment: .leading, spacing: 12) {
                        Text("This Week").font(.headline).foregroundStyle(.white)
                        HStack(alignment: .bottom, spacing: 8) {
                            ForEach(["M","T","W","T","F","S","S"], id: \.self) { day in
                                VStack(spacing: 4) {
                                    RoundedRectangle(cornerRadius: 4)
                                        .fill(LinearGradient(colors: [accent, .cyan], startPoint: .bottom, endPoint: .top))
                                        .frame(width: 30, height: CGFloat.random(in: 40...120))
                                    Text(day).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 16).fill(surface))
                    .padding(.horizontal)

                    // Streak
                    HStack {
                        Image(systemName: "flame.fill").font(.title).foregroundStyle(.orange)
                        VStack(alignment: .leading) {
                            Text("12 Day Streak").font(.headline).foregroundStyle(.white)
                            Text("Keep it going!").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 16).fill(surface))
                    .padding(.horizontal)
                }
                .padding(.vertical)
            }
            .background(bg)
            .navigationTitle("Dashboard")
        }
    }
}

struct StatRing: View {
    let label: String; let value: String; let total: String; let progress: Double; let color: Color
    var body: some View {
        VStack(spacing: 6) {
            ZStack {
                Circle().stroke(color.opacity(0.2), lineWidth: 8)
                Circle().trim(from: 0, to: progress).stroke(color, style: StrokeStyle(lineWidth: 8, lineCap: .round)).rotationEffect(.degrees(-90))
                Text(value).font(.system(size: 14, weight: .bold, design: .monospaced)).foregroundStyle(.white)
            }.frame(width: 70, height: 70)
            Text(label).font(.caption2).foregroundStyle(.secondary)
        }
    }
}

// MARK: - Workouts

struct WorkoutsView: View {
    let workouts = [
        ("Running", "figure.run", "32 min", "320 cal", "Today"),
        ("Weight Training", "dumbbell.fill", "45 min", "280 cal", "Yesterday"),
        ("Yoga", "figure.yoga", "30 min", "150 cal", "Oct 5"),
        ("HIIT", "bolt.fill", "20 min", "400 cal", "Oct 4"),
        ("Swimming", "figure.pool.swim", "40 min", "350 cal", "Oct 3"),
    ]

    var body: some View {
        NavigationStack {
            List {
                ForEach(workouts, id: \.0) { w in
                    HStack(spacing: 14) {
                        Image(systemName: w.1)
                            .font(.title2).foregroundStyle(accent)
                            .frame(width: 44, height: 44)
                            .background(Circle().fill(accent.opacity(0.15)))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(w.0).font(.subheadline.bold()).foregroundStyle(.white)
                            Text("\(w.2) · \(w.3)").font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Text(w.4).font(.caption2).foregroundStyle(.secondary)
                    }
                    .listRowBackground(surface)
                }
            }
            .scrollContentBackground(.hidden)
            .background(bg)
            .navigationTitle("Workouts")
        }
    }
}

// MARK: - Progress

struct ProgressView_: View {
    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Weight chart
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Weight (30 days)").font(.headline).foregroundStyle(.white)
                        HStack(alignment: .bottom, spacing: 4) {
                            ForEach(0..<30, id: \.self) { i in
                                let h = 60.0 + sin(Double(i) * 0.3) * 20 - Double(i) * 0.5
                                RoundedRectangle(cornerRadius: 2)
                                    .fill(accent.opacity(0.7))
                                    .frame(width: 8, height: max(20, h))
                            }
                        }
                        HStack { Text("175 lbs").font(.caption).foregroundStyle(accent); Spacer(); Text("→ 170 lbs").font(.caption).foregroundStyle(accent) }
                    }
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 16).fill(surface))
                    .padding(.horizontal)

                    // Records
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Personal Records").font(.headline).foregroundStyle(.white)
                        ForEach([("Bench Press", "185 lbs"), ("5K Run", "22:30"), ("Deadlift", "275 lbs"), ("Plank", "3:45")], id: \.0) { pr in
                            HStack {
                                Text(pr.0).font(.subheadline).foregroundStyle(.white)
                                Spacer()
                                Text(pr.1).font(.subheadline.bold()).foregroundStyle(accent)
                            }
                            Divider().overlay(Color.white.opacity(0.1))
                        }
                    }
                    .padding()
                    .background(RoundedRectangle(cornerRadius: 16).fill(surface))
                    .padding(.horizontal)
                }
                .padding(.vertical)
            }
            .background(bg)
            .navigationTitle("Progress")
        }
    }
}
