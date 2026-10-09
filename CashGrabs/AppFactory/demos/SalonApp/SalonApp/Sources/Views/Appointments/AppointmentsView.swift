import SwiftUI

struct AppointmentsView: View {
    @State private var selectedTab = 0

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Segment Control
                segmentControl
                    .padding(.top, 8)

                ScrollView(showsIndicators: false) {
                    LazyVStack(spacing: 14) {
                        if selectedTab == 0 {
                            ForEach(SampleData.upcomingAppointments) { appointment in
                                AppointmentCard(appointment: appointment)
                            }
                        } else {
                            ForEach(SampleData.pastAppointments) { appointment in
                                AppointmentCard(appointment: appointment)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.top, 16)
                    .padding(.bottom, 30)
                }
            }
            .background(Theme.surfaceBackground)
            .navigationTitle("My Bookings")
            .navigationBarTitleDisplayMode(.large)
        }
    }

    private var segmentControl: some View {
        HStack(spacing: 0) {
            ForEach(["Upcoming", "Past"].indices, id: \.self) { index in
                Button(action: {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        selectedTab = index
                    }
                }) {
                    VStack(spacing: 8) {
                        Text(["Upcoming", "Past"][index])
                            .font(Theme.bodySemibold(15))
                            .foregroundStyle(selectedTab == index ? Theme.roseGold : Theme.textSecondary)
                        Rectangle()
                            .fill(selectedTab == index ? Theme.roseGold : Color.clear)
                            .frame(height: 2)
                    }
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding(.horizontal, 20)
    }
}

// MARK: - Appointment Card
struct AppointmentCard: View {
    let appointment: Appointment

    private var statusColor: Color {
        switch appointment.status {
        case .confirmed: return Color(red: 0.2, green: 0.7, blue: 0.4)
        case .completed: return Color(red: 0.3, green: 0.5, blue: 0.8)
        case .cancelled: return Color(red: 0.85, green: 0.3, blue: 0.3)
        }
    }

    private var statusIcon: String {
        switch appointment.status {
        case .confirmed: return "checkmark.circle.fill"
        case .completed: return "checkmark.seal.fill"
        case .cancelled: return "xmark.circle.fill"
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Top section
            HStack(spacing: 14) {
                // Date badge
                VStack(spacing: 1) {
                    Text(appointment.date.components(separatedBy: " ").first ?? "")
                        .font(Theme.bodySemibold(10))
                        .foregroundStyle(Theme.roseGold)
                    Text(appointment.date.components(separatedBy: " ")[safe: 1]?.replacingOccurrences(of: ",", with: "") ?? "")
                        .font(.system(size: 24, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.textPrimary)
                }
                .frame(width: 54, height: 54)
                .background(Theme.softPink)
                .clipShape(RoundedRectangle(cornerRadius: 12))

                VStack(alignment: .leading, spacing: 4) {
                    Text(appointment.serviceName)
                        .font(Theme.bodySemibold(16))
                        .foregroundStyle(Theme.textPrimary)

                    HStack(spacing: 12) {
                        Label(appointment.time, systemImage: "clock")
                            .font(Theme.body(12))
                            .foregroundStyle(Theme.textSecondary)
                        Label("\(appointment.duration) min", systemImage: "hourglass")
                            .font(Theme.body(12))
                            .foregroundStyle(Theme.textSecondary)
                    }
                }

                Spacer()

                Text("$\(Int(appointment.price))")
                    .font(Theme.serifHeading(18))
                    .foregroundStyle(Theme.roseGold)
            }

            Divider()
                .padding(.vertical, 12)

            // Bottom section
            HStack {
                HStack(spacing: 6) {
                    Circle()
                        .fill(Theme.lightRoseGold)
                        .frame(width: 24, height: 24)
                        .overlay(
                            Text(String(appointment.stylistName.prefix(1)))
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(Theme.deepRose)
                        )
                    Text(appointment.stylistName)
                        .font(Theme.body(13))
                        .foregroundStyle(Theme.textSecondary)
                }

                Spacer()

                HStack(spacing: 5) {
                    Image(systemName: statusIcon)
                        .font(.system(size: 12))
                    Text(appointment.status.rawValue)
                        .font(Theme.bodySemibold(12))
                }
                .foregroundStyle(statusColor)
                .padding(.horizontal, 12)
                .padding(.vertical, 5)
                .background(statusColor.opacity(0.1))
                .clipShape(Capsule())
            }

            // Action buttons for confirmed
            if appointment.status == .confirmed {
                HStack(spacing: 10) {
                    Button(action: {}) {
                        HStack(spacing: 5) {
                            Image(systemName: "pencil")
                                .font(.system(size: 12))
                            Text("Reschedule")
                                .font(Theme.bodySemibold(12))
                        }
                        .foregroundStyle(Theme.roseGold)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Theme.softPink)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: {}) {
                        HStack(spacing: 5) {
                            Image(systemName: "xmark")
                                .font(.system(size: 12))
                            Text("Cancel")
                                .font(Theme.bodySemibold(12))
                        }
                        .foregroundStyle(Theme.textSecondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Color.gray.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
                .padding(.top, 12)
            }
        }
        .padding(16)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
    }
}

// Safe array subscript
extension Collection {
    subscript(safe index: Index) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}
