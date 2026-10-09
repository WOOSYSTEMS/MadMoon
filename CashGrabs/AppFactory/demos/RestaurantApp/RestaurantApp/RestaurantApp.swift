import SwiftUI

@main
struct RestaurantApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                HomeView().tabItem { Label("Home", systemImage: "house.fill") }
                MenuView().tabItem { Label("Menu", systemImage: "list.bullet") }
                CartView().tabItem { Label("Cart", systemImage: "cart.fill") }
                Text("Profile").tabItem { Label("Profile", systemImage: "person.fill") }
            }
            .tint(Color(red: 1.0, green: 0.42, blue: 0.21))
        }
    }
}

// MARK: - Home

struct HomeView: View {
    let accent = Color(red: 1.0, green: 0.42, blue: 0.21)
    let bg = Color(red: 1.0, green: 0.96, blue: 0.88)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Hero
                    ZStack(alignment: .bottomLeading) {
                        RoundedRectangle(cornerRadius: 16)
                            .fill(LinearGradient(colors: [accent, .orange], startPoint: .topLeading, endPoint: .bottomTrailing))
                            .frame(height: 200)
                        VStack(alignment: .leading) {
                            Text("Welcome to")
                                .font(.subheadline).foregroundStyle(.white.opacity(0.8))
                            Text("Sakura Kitchen")
                                .font(.largeTitle.bold()).foregroundStyle(.white)
                            Text("Fresh Japanese Fusion")
                                .font(.caption).foregroundStyle(.white.opacity(0.7))
                        }.padding(20)
                    }.padding(.horizontal)

                    // Categories
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 12) {
                            ForEach(["Sushi", "Ramen", "Tempura", "Donburi", "Desserts"], id: \.self) { cat in
                                VStack(spacing: 6) {
                                    Circle().fill(accent.opacity(0.15)).frame(width: 60, height: 60)
                                        .overlay(Image(systemName: "fork.knife").foregroundStyle(accent))
                                    Text(cat).font(.caption2).foregroundStyle(.secondary)
                                }
                            }
                        }.padding(.horizontal)
                    }

                    // Featured
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Featured").font(.title3.bold()).padding(.horizontal)
                        ForEach(["Dragon Roll", "Tonkotsu Ramen", "Chicken Katsu"], id: \.self) { dish in
                            HStack(spacing: 14) {
                                RoundedRectangle(cornerRadius: 12).fill(accent.opacity(0.12))
                                    .frame(width: 80, height: 80)
                                    .overlay(Image(systemName: "takeoutbag.and.cup.and.straw.fill").foregroundStyle(accent))
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(dish).font(.headline)
                                    Text("Fresh ingredients, handmade").font(.caption).foregroundStyle(.secondary)
                                    Text("$14.99").font(.subheadline.bold()).foregroundStyle(accent)
                                }
                                Spacer()
                                Button { } label: {
                                    Image(systemName: "plus.circle.fill").font(.title2).foregroundStyle(accent)
                                }
                            }
                            .padding(.horizontal)
                            .padding(.vertical, 8)
                            .background(RoundedRectangle(cornerRadius: 12).fill(.white).shadow(color: .black.opacity(0.05), radius: 4, y: 2))
                            .padding(.horizontal)
                        }
                    }
                }
                .padding(.bottom, 20)
            }
            .background(bg)
            .navigationTitle("Sakura Kitchen")
        }
    }
}

// MARK: - Menu

struct MenuView: View {
    let accent = Color(red: 1.0, green: 0.42, blue: 0.21)
    let items = [
        ("Appetizers", ["Edamame $5.99", "Gyoza $7.99", "Miso Soup $4.99"]),
        ("Mains", ["Salmon Sashimi $18.99", "Beef Teriyaki $16.99", "Pad Thai $14.99"]),
        ("Desserts", ["Mochi Ice Cream $6.99", "Matcha Cake $8.99"]),
    ]

    var body: some View {
        NavigationStack {
            List {
                ForEach(items, id: \.0) { section in
                    Section(section.0) {
                        ForEach(section.1, id: \.self) { item in
                            HStack {
                                RoundedRectangle(cornerRadius: 8).fill(accent.opacity(0.1))
                                    .frame(width: 50, height: 50)
                                    .overlay(Image(systemName: "fork.knife").foregroundStyle(accent))
                                Text(item).font(.subheadline)
                                Spacer()
                                Button { } label: {
                                    Text("Add").font(.caption.bold())
                                        .padding(.horizontal, 12).padding(.vertical, 6)
                                        .background(accent).foregroundStyle(.white)
                                        .clipShape(Capsule())
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Menu")
        }
    }
}

// MARK: - Cart

struct CartView: View {
    let accent = Color(red: 1.0, green: 0.42, blue: 0.21)

    var body: some View {
        NavigationStack {
            VStack {
                List {
                    ForEach(["Dragon Roll x2", "Tonkotsu Ramen x1", "Mochi Ice Cream x3"], id: \.self) { item in
                        HStack {
                            RoundedRectangle(cornerRadius: 8).fill(accent.opacity(0.1))
                                .frame(width: 50, height: 50)
                                .overlay(Image(systemName: "takeoutbag.and.cup.and.straw.fill").foregroundStyle(accent))
                            VStack(alignment: .leading) {
                                Text(item).font(.subheadline.bold())
                                Text("$14.99 each").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Text("$29.98").font(.subheadline.bold())
                        }
                    }
                }

                VStack(spacing: 8) {
                    HStack { Text("Subtotal"); Spacer(); Text("$65.94").bold() }
                    HStack { Text("Delivery"); Spacer(); Text("$4.99").foregroundStyle(.secondary) }
                    Divider()
                    HStack { Text("Total").font(.title3.bold()); Spacer(); Text("$70.93").font(.title3.bold()).foregroundStyle(accent) }

                    Button { } label: {
                        Text("Place Order")
                            .font(.headline).foregroundStyle(.white)
                            .frame(maxWidth: .infinity).padding()
                            .background(accent).clipShape(RoundedRectangle(cornerRadius: 14))
                    }
                }
                .padding()
            }
            .navigationTitle("Cart")
        }
    }
}
