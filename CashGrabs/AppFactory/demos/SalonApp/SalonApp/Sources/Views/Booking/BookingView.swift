import SwiftUI

struct BookingView: View {
    let service: SalonService
    @Environment(\.dismiss) private var dismiss
    @State private var selectedDate = Date()
    @State private var selectedSlot: TimeSlot?
    @State private var showConfirmation = false

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(spacing: 24) {
                    // Service Summary
                    serviceSummary

                    // Date Picker
                    dateSection

                    // Time Slots
                    timeSlotsSection

                    // Confirm Button
                    confirmButton
                }
                .padding(.bottom, 40)
            }
            .background(Theme.surfaceBackground)
            .navigationTitle("Book Appointment")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: { dismiss() }) {
                        Image(systemName: "xmark.circle.fill")
                            .font(.system(size: 22))
                            .foregroundStyle(Theme.textSecondary.opacity(0.5))
                    }
                }
            }
            .alert("Booking Confirmed!", isPresented: $showConfirmation) {
                Button("Done") { dismiss() }
            } message: {
                Text("Your \(service.name) appointment has been booked successfully. We look forward to seeing you!")
            }
        }
    }

    // MARK: - Service Summary
    private var serviceSummary: some View {
        HStack(spacing: 16) {
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(
                        LinearGradient(
                            colors: [Theme.roseGold.opacity(0.2), Theme.softPink],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 64, height: 64)
                Image(systemName: service.iconName)
                    .font(.system(size: 24))
                    .foregroundStyle(Theme.roseGold)
            }

            VStack(alignment: .leading, spacing: 5) {
                Text(service.name)
                    .font(Theme.serifHeading(18))
                    .foregroundStyle(Theme.textPrimary)

                HStack(spacing: 14) {
                    Label("\(service.duration) min", systemImage: "clock")
                        .font(Theme.body(13))
                        .foregroundStyle(Theme.textSecondary)
                    Label(service.stylistName, systemImage: "person")
                        .font(Theme.body(13))
                        .foregroundStyle(Theme.textSecondary)
                }
            }

            Spacer()

            Text("$\(Int(service.price))")
                .font(Theme.serifTitle(22))
                .foregroundStyle(Theme.roseGold)
        }
        .padding(18)
        .background(Theme.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
        .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
        .padding(.horizontal, 20)
        .padding(.top, 12)
    }

    // MARK: - Date Section
    private var dateSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Select Date")
                .font(Theme.serifHeading(18))
                .foregroundStyle(Theme.textPrimary)
                .padding(.horizontal, 20)

            DatePicker(
                "Select a date",
                selection: $selectedDate,
                in: Date()...,
                displayedComponents: .date
            )
            .datePickerStyle(.graphical)
            .tint(Theme.roseGold)
            .padding(16)
            .background(Theme.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: Theme.cardCornerRadius))
            .shadow(color: .black.opacity(0.06), radius: Theme.cardShadowRadius, y: 4)
            .padding(.horizontal, 20)
        }
    }

    // MARK: - Time Slots
    private var timeSlotsSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Text("Available Times")
                    .font(Theme.serifHeading(18))
                    .foregroundStyle(Theme.textPrimary)
                Spacer()
                HStack(spacing: 8) {
                    Circle().fill(Theme.roseGold).frame(width: 8, height: 8)
                    Text("Available")
                        .font(Theme.body(11))
                        .foregroundStyle(Theme.textSecondary)
                    Circle().fill(Color.gray.opacity(0.3)).frame(width: 8, height: 8)
                    Text("Booked")
                        .font(Theme.body(11))
                        .foregroundStyle(Theme.textSecondary)
                }
            }
            .padding(.horizontal, 20)

            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 4), spacing: 10) {
                ForEach(SampleData.timeSlots) { slot in
                    Button(action: {
                        if slot.available {
                            selectedSlot = slot
                        }
                    }) {
                        Text(slot.time)
                            .font(Theme.bodySemibold(12))
                            .foregroundStyle(
                                !slot.available ? Theme.textSecondary.opacity(0.4) :
                                selectedSlot == slot ? .white :
                                Theme.textPrimary
                            )
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 12)
                            .background(
                                RoundedRectangle(cornerRadius: 10)
                                    .fill(
                                        !slot.available ? Color.gray.opacity(0.08) :
                                        selectedSlot == slot ? Theme.roseGold :
                                        Theme.cardBackground
                                    )
                            )
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .strokeBorder(
                                        !slot.available ? Color.clear :
                                        selectedSlot == slot ? Color.clear :
                                        Theme.lightRoseGold.opacity(0.4),
                                        lineWidth: 1
                                    )
                            )
                    }
                    .disabled(!slot.available)
                }
            }
            .padding(.horizontal, 20)
        }
    }

    // MARK: - Confirm Button
    private var confirmButton: some View {
        VStack(spacing: 12) {
            if let slot = selectedSlot {
                HStack {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Your Selection")
                            .font(Theme.body(12))
                            .foregroundStyle(Theme.textSecondary)
                        Text("\(service.name) at \(slot.time)")
                            .font(Theme.bodySemibold(15))
                            .foregroundStyle(Theme.textPrimary)
                    }
                    Spacer()
                    Text("$\(Int(service.price))")
                        .font(Theme.serifHeading(20))
                        .foregroundStyle(Theme.roseGold)
                }
                .padding(16)
                .background(Theme.softPink.opacity(0.5))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }

            Button(action: {
                showConfirmation = true
            }) {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                    Text("Confirm Booking")
                        .font(Theme.bodySemibold(16))
                }
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 16)
                .background(
                    Capsule()
                        .fill(
                            selectedSlot != nil ?
                            LinearGradient(colors: [Theme.roseGold, Theme.deepRose], startPoint: .leading, endPoint: .trailing) :
                            LinearGradient(colors: [Color.gray.opacity(0.4), Color.gray.opacity(0.3)], startPoint: .leading, endPoint: .trailing)
                        )
                )
            }
            .disabled(selectedSlot == nil)
        }
        .padding(.horizontal, 20)
    }
}
