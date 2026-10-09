import SwiftUI

struct ServicesView: View {
    @State private var selectedCategory: String = "All"
    @State private var showBooking = false
    @State private var selectedService: SalonService?

    private let allCategories = ["All", "Hair", "Nails", "Facial", "Massage"]

    private var filteredServices: [SalonService] {
        if selectedCategory == "All" {
            return SampleData.services
        }
        return SampleData.services.filter { $0.category == selectedCategory }
    }

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 20) {
                    // Category Filter
                    categoryFilter

                    // Service Cards
                    LazyVStack(spacing: 16) {
                        ForEach(filteredServices) { service in
                            ServiceCard(service: service) {
                                selectedService = service
                                showBooking = true
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                }
                .padding(.bottom, 30)
            }
            .background(Theme.surfaceBackground)
            .navigationTitle("Services")
            .navigationBarTitleDisplayMode(.large)
            .sheet(isPresented: $showBooking) {
                if let service = selectedService {
                    BookingView(service: service)
                }
            }
        }
    }

    private var categoryFilter: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(allCategories, id: \.self) { category in
                    Button(action: {
                        withAnimation(.easeInOut(duration: 0.2)) {
                            selectedCategory = category
                        }
                    }) {
                        Text(category)
                            .font(Theme.bodySemibold(14))
                            .foregroundStyle(selectedCategory == category ? .white : Theme.textPrimary)
                            .padding(.horizontal, 20)
                            .padding(.vertical, 10)
                            .background(
                                Capsule()
                                    .fill(selectedCategory == category ? Theme.roseGold : Theme.cardBackground)
                            )
                            .shadow(color: .black.opacity(selectedCategory == category ? 0.1 : 0.04), radius: 4, y: 2)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 8)
        }
    }
}

// MARK: - Service Card
struct ServiceCard: View {
    let service: SalonService
    let onBook: () -> Void

    var body: some View {
        HStack(spacing: 16) {
            // Icon
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(Theme.softPink)
                    .frame(width: 60, height: 60)
                Image(systemName: service.iconName)
                    .font(.system(size: 22))
                    .foregroundStyle(Theme.roseGold)
            }

            VStack(alignment: .leading, spacing: 5) {
                Text(service.name)
                    .font(Theme.bodySemibold(16))
                    .foregroundStyle(Theme.textPrimary)

                Text(service.description)
                    .font(Theme.body(12))
                    .foregroundStyle(Theme.textSecondary)
                    .lineLimit(1)

                HStack(spacing: 12) {
                    Label("\(service.duration) min", systemImage: "clock")
                        .font(Theme.body(12))
                        .foregroundStyle(Theme.textSecondary)

                    HStack(spacing: 4) {
                        Circle()
                            .fill(Theme.lightRoseGold)
                            .frame(width: 18, height: 18)
                            .overlay(
                                Text(String(service.stylistName.prefix(1)))
                                    .font(.system(size: 9, weight: .semibold))
                                    .foregroundStyle(Theme.deepRose)
                            )
                        Text(service.stylistName.components(separatedBy: " ").first ?? "")
                            .font(Theme.body(12))
                            .foregroundStyle(Theme.textSecondary)
                    }
                }
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 8) {
                Text("$\(Int(service.price))")
                    .font(Theme.serifHeading(18))
                    .foregroundStyle(Theme.roseGold)

                Button(action: onBook) {
                    Text("Book")
                        .font(Theme.bodySemibold(12))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 18)
                        .padding(.vertical, 7)
                        .background(Theme.roseGold)
                        .clipShape(Capsule())
                }
            }
        }
        .padding(16)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
    }
}
