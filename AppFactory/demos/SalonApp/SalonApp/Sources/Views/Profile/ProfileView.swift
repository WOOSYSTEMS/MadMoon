import SwiftUI

struct ProfileView: View {
    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 24) {
                    // Profile Header
                    profileHeader

                    // Stats
                    statsRow

                    // Menu Items
                    menuSection

                    // Loyalty Card
                    loyaltyCard
                }
                .padding(.bottom, 30)
            }
            .background(Theme.surfaceBackground)
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.large)
        }
    }

    private var profileHeader: some View {
        VStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Theme.roseGold, Theme.deepRose],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 90, height: 90)
                Text("JM")
                    .font(.system(size: 32, weight: .semibold, design: .serif))
                    .foregroundStyle(.white)
            }

            VStack(spacing: 4) {
                Text("Jessica Mitchell")
                    .font(Theme.serifHeading(22))
                    .foregroundStyle(Theme.textPrimary)
                Text("Member since 2024")
                    .font(Theme.body(13))
                    .foregroundStyle(Theme.textSecondary)
            }

            HStack(spacing: 5) {
                Image(systemName: "crown.fill")
                    .font(.system(size: 12))
                Text("Gold Member")
                    .font(Theme.bodySemibold(13))
            }
            .foregroundStyle(Theme.roseGold)
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
            .background(Theme.softPink)
            .clipShape(Capsule())
        }
        .padding(.top, 12)
    }

    private var statsRow: some View {
        HStack(spacing: 0) {
            statItem(value: "28", label: "Visits")
            Divider().frame(height: 40)
            statItem(value: "$3,240", label: "Spent")
            Divider().frame(height: 40)
            statItem(value: "450", label: "Points")
        }
        .padding(.vertical, 18)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
        .padding(.horizontal, 20)
    }

    private func statItem(value: String, label: String) -> some View {
        VStack(spacing: 4) {
            Text(value)
                .font(Theme.serifHeading(20))
                .foregroundStyle(Theme.textPrimary)
            Text(label)
                .font(Theme.body(12))
                .foregroundStyle(Theme.textSecondary)
        }
        .frame(maxWidth: .infinity)
    }

    private var menuSection: some View {
        VStack(spacing: 2) {
            menuItem(icon: "person.fill", title: "Personal Info", subtitle: "Name, email, phone")
            menuItem(icon: "creditcard.fill", title: "Payment Methods", subtitle: "Visa ending in 4832")
            menuItem(icon: "bell.fill", title: "Notifications", subtitle: "Reminders & offers")
            menuItem(icon: "heart.fill", title: "Favorites", subtitle: "Saved services & stylists")
            menuItem(icon: "gift.fill", title: "Rewards", subtitle: "450 points available")
            menuItem(icon: "gearshape.fill", title: "Settings", subtitle: "Preferences & privacy")
        }
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
        .padding(.horizontal, 20)
    }

    private func menuItem(icon: String, title: String, subtitle: String) -> some View {
        HStack(spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Theme.softPink)
                    .frame(width: 40, height: 40)
                Image(systemName: icon)
                    .font(.system(size: 16))
                    .foregroundStyle(Theme.roseGold)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(Theme.bodySemibold(15))
                    .foregroundStyle(Theme.textPrimary)
                Text(subtitle)
                    .font(Theme.body(12))
                    .foregroundStyle(Theme.textSecondary)
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Theme.lightRoseGold)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
    }

    private var loyaltyCard: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 20)
                .fill(
                    LinearGradient(
                        colors: [Theme.roseGold, Theme.deepRose, Color(red: 0.45, green: 0.22, blue: 0.28)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Luxe Rewards")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(.white.opacity(0.7))
                        Text("Gold Member")
                            .font(.system(size: 20, weight: .bold, design: .serif))
                            .foregroundStyle(.white)
                    }
                    Spacer()
                    Image(systemName: "crown.fill")
                        .font(.system(size: 24))
                        .foregroundStyle(.white.opacity(0.8))
                }

                Spacer()

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("450 / 500 points")
                            .font(Theme.bodySemibold(13))
                            .foregroundStyle(.white)
                        Spacer()
                        Text("90%")
                            .font(Theme.bodySemibold(12))
                            .foregroundStyle(.white.opacity(0.7))
                    }
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(.white.opacity(0.2))
                            RoundedRectangle(cornerRadius: 4)
                                .fill(.white.opacity(0.8))
                                .frame(width: geo.size.width * 0.9)
                        }
                    }
                    .frame(height: 6)
                    Text("50 points to Platinum")
                        .font(Theme.body(11))
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
            .padding(22)
        }
        .frame(height: 175)
        .padding(.horizontal, 20)
    }
}
