import SwiftUI

struct HomeView: View {
    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 24) {
                    // Header
                    headerSection

                    // Next Appointment Reminder
                    appointmentReminder

                    // Categories
                    categoriesSection

                    // Featured Stylists
                    featuredStylistsSection
                }
                .padding(.bottom, 30)
            }
            .background(Theme.surfaceBackground)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Welcome back,")
                            .font(Theme.body(13))
                            .foregroundStyle(Theme.textSecondary)
                        Text("Jessica")
                            .font(Theme.serifHeading(18))
                            .foregroundStyle(Theme.textPrimary)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: {}) {
                        Image(systemName: "bell.badge")
                            .font(.system(size: 18))
                            .foregroundStyle(Theme.roseGold)
                    }
                }
            }
        }
    }

    // MARK: - Header
    private var headerSection: some View {
        VStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 24)
                    .fill(
                        LinearGradient(
                            colors: [Theme.roseGold, Theme.deepRose],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(height: 180)

                VStack(spacing: 8) {
                    Image(systemName: "crown.fill")
                        .font(.system(size: 28))
                        .foregroundStyle(.white.opacity(0.9))

                    Text("Luxe Beauty Studio")
                        .font(.system(size: 28, weight: .bold, design: .serif))
                        .foregroundStyle(.white)

                    Text("Where elegance meets expertise")
                        .font(Theme.body(14))
                        .foregroundStyle(.white.opacity(0.85))

                    HStack(spacing: 4) {
                        ForEach(0..<5, id: \.self) { _ in
                            Image(systemName: "star.fill")
                                .font(.system(size: 10))
                                .foregroundStyle(.white.opacity(0.9))
                        }
                        Text("4.9")
                            .font(Theme.bodySemibold(12))
                            .foregroundStyle(.white.opacity(0.9))
                        Text("(1,247 reviews)")
                            .font(Theme.body(11))
                            .foregroundStyle(.white.opacity(0.7))
                    }
                }
            }
            .padding(.horizontal, 20)
        }
        .padding(.top, 8)
    }

    // MARK: - Appointment Reminder
    private var appointmentReminder: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Next Appointment")
                    .font(Theme.serifHeading(18))
                    .foregroundStyle(Theme.textPrimary)
                Spacer()
                Image(systemName: "clock.fill")
                    .foregroundStyle(Theme.roseGold)
                    .font(.system(size: 14))
            }

            HStack(spacing: 14) {
                // Date badge
                VStack(spacing: 2) {
                    Text("OCT")
                        .font(Theme.bodySemibold(10))
                        .foregroundStyle(Theme.roseGold)
                    Text("8")
                        .font(.system(size: 28, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.textPrimary)
                    Text("THU")
                        .font(Theme.bodySemibold(10))
                        .foregroundStyle(Theme.textSecondary)
                }
                .frame(width: 60, height: 72)
                .background(Theme.softPink)
                .clipShape(RoundedRectangle(cornerRadius: 12))

                VStack(alignment: .leading, spacing: 4) {
                    Text("Balayage Color")
                        .font(Theme.bodySemibold(16))
                        .foregroundStyle(Theme.textPrimary)
                    HStack(spacing: 12) {
                        Label("10:00 AM", systemImage: "clock")
                            .font(Theme.body(13))
                            .foregroundStyle(Theme.textSecondary)
                        Label("2 hrs", systemImage: "hourglass")
                            .font(Theme.body(13))
                            .foregroundStyle(Theme.textSecondary)
                    }
                    Text("with Sophia Laurent")
                        .font(Theme.body(13))
                        .foregroundStyle(Theme.roseGold)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Theme.lightRoseGold)
            }
        }
        .padding(18)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
        .padding(.horizontal, 20)
    }

    // MARK: - Categories
    private var categoriesSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Our Services")
                .font(Theme.serifHeading(20))
                .foregroundStyle(Theme.textPrimary)
                .padding(.horizontal, 20)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 14) {
                    ForEach(SampleData.categories) { category in
                        CategoryCard(category: category)
                    }
                }
                .padding(.horizontal, 20)
            }
        }
    }

    // MARK: - Featured Stylists
    private var featuredStylistsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Featured Stylists")
                    .font(Theme.serifHeading(20))
                    .foregroundStyle(Theme.textPrimary)
                Spacer()
                Text("View All")
                    .font(Theme.bodySemibold(13))
                    .foregroundStyle(Theme.roseGold)
            }
            .padding(.horizontal, 20)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 16) {
                    ForEach(SampleData.stylists) { stylist in
                        StylistCard(stylist: stylist)
                    }
                }
                .padding(.horizontal, 20)
            }
        }
    }
}

// MARK: - Category Card
struct CategoryCard: View {
    let category: ServiceCategory

    private var categoryColor: Color {
        switch category.name {
        case "Hair": return Color(red: 0.78, green: 0.52, blue: 0.56)
        case "Nails": return Color(red: 0.82, green: 0.55, blue: 0.62)
        case "Facial": return Color(red: 0.68, green: 0.50, blue: 0.58)
        case "Massage": return Color(red: 0.58, green: 0.60, blue: 0.52)
        default: return Theme.roseGold
        }
    }

    var body: some View {
        VStack(spacing: 10) {
            ZStack {
                Circle()
                    .fill(categoryColor.opacity(0.15))
                    .frame(width: 56, height: 56)
                Image(systemName: category.icon)
                    .font(.system(size: 22))
                    .foregroundStyle(categoryColor)
            }
            Text(category.name)
                .font(Theme.bodySemibold(13))
                .foregroundStyle(Theme.textPrimary)
        }
        .frame(width: 85, height: 105)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .shadow(color: .black.opacity(0.05), radius: 6, y: 3)
    }
}

// MARK: - Stylist Card
struct StylistCard: View {
    let stylist: Stylist

    var body: some View {
        VStack(spacing: 12) {
            // Avatar
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Theme.roseGold.opacity(0.3), Theme.softPink],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 72, height: 72)
                Text(stylist.initials)
                    .font(.system(size: 22, weight: .semibold, design: .serif))
                    .foregroundStyle(Theme.deepRose)
            }

            VStack(spacing: 3) {
                Text(stylist.name)
                    .font(Theme.bodySemibold(14))
                    .foregroundStyle(Theme.textPrimary)
                    .lineLimit(1)

                Text(stylist.specialty)
                    .font(Theme.body(11))
                    .foregroundStyle(Theme.textSecondary)
                    .lineLimit(1)
            }

            HStack(spacing: 3) {
                Image(systemName: "star.fill")
                    .font(.system(size: 10))
                    .foregroundStyle(.orange)
                Text(String(format: "%.1f", stylist.rating))
                    .font(Theme.bodySemibold(12))
                    .foregroundStyle(Theme.textPrimary)
                Text("(\(stylist.reviewCount))")
                    .font(Theme.body(11))
                    .foregroundStyle(Theme.textSecondary)
            }
        }
        .frame(width: 140, height: 175)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
    }
}
