import SwiftUI

struct MainTabView: View {
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            HomeView()
                .tabItem {
                    Image(systemName: "house.fill")
                    Text("Home")
                }
                .tag(0)

            ServicesView()
                .tabItem {
                    Image(systemName: "sparkles")
                    Text("Services")
                }
                .tag(1)

            AppointmentsView()
                .tabItem {
                    Image(systemName: "calendar")
                    Text("Bookings")
                }
                .tag(2)

            ProfileView()
                .tabItem {
                    Image(systemName: "person.fill")
                    Text("Profile")
                }
                .tag(3)
        }
        .tint(Theme.roseGold)
    }
}
