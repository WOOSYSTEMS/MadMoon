import Foundation

// MARK: - Service Category
struct ServiceCategory: Identifiable {
    let id = UUID()
    let name: String
    let icon: String
    let color: String
}

// MARK: - Service
struct SalonService: Identifiable {
    let id = UUID()
    let name: String
    let category: String
    let duration: Int // minutes
    let price: Double
    let stylistName: String
    let description: String
    let iconName: String
}

// MARK: - Stylist
struct Stylist: Identifiable {
    let id = UUID()
    let name: String
    let specialty: String
    let rating: Double
    let reviewCount: Int
    let initials: String
}

// MARK: - Time Slot
struct TimeSlot: Identifiable, Hashable {
    let id = UUID()
    let time: String
    let available: Bool

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }

    static func == (lhs: TimeSlot, rhs: TimeSlot) -> Bool {
        lhs.id == rhs.id
    }
}

// MARK: - Appointment
struct Appointment: Identifiable {
    let id = UUID()
    let serviceName: String
    let stylistName: String
    let date: String
    let time: String
    let status: AppointmentStatus
    let price: Double
    let duration: Int
}

enum AppointmentStatus: String {
    case confirmed = "Confirmed"
    case completed = "Completed"
    case cancelled = "Cancelled"

    var color: String {
        switch self {
        case .confirmed: return "green"
        case .completed: return "blue"
        case .cancelled: return "red"
        }
    }
}

// MARK: - Sample Data
enum SampleData {
    static let categories: [ServiceCategory] = [
        ServiceCategory(name: "Hair", icon: "scissors", color: "hair"),
        ServiceCategory(name: "Nails", icon: "hand.raised.fingers.spread", color: "nails"),
        ServiceCategory(name: "Facial", icon: "sparkles", color: "facial"),
        ServiceCategory(name: "Massage", icon: "leaf.fill", color: "massage"),
    ]

    static let services: [SalonService] = [
        SalonService(name: "Signature Blowout", category: "Hair", duration: 45, price: 85, stylistName: "Sophia Laurent", description: "Luxurious blowout with premium products", iconName: "scissors"),
        SalonService(name: "Balayage Color", category: "Hair", duration: 120, price: 250, stylistName: "Sophia Laurent", description: "Hand-painted highlights for a natural sun-kissed look", iconName: "paintbrush.fill"),
        SalonService(name: "Keratin Treatment", category: "Hair", duration: 90, price: 350, stylistName: "Sophia Laurent", description: "Smoothing treatment for frizz-free hair", iconName: "wind"),
        SalonService(name: "Precision Haircut", category: "Hair", duration: 60, price: 120, stylistName: "Mia Chen", description: "Expert cut tailored to your face shape", iconName: "scissors"),
        SalonService(name: "Gel Manicure", category: "Nails", duration: 45, price: 55, stylistName: "Isabella Rose", description: "Long-lasting gel polish with cuticle care", iconName: "hand.raised.fingers.spread"),
        SalonService(name: "Spa Pedicure", category: "Nails", duration: 60, price: 75, stylistName: "Isabella Rose", description: "Relaxing foot treatment with exfoliation", iconName: "drop.triangle.fill"),
        SalonService(name: "Nail Art Design", category: "Nails", duration: 75, price: 95, stylistName: "Isabella Rose", description: "Custom artistic nail designs", iconName: "paintpalette.fill"),
        SalonService(name: "HydraFacial", category: "Facial", duration: 60, price: 185, stylistName: "Emma Dubois", description: "Deep cleansing and hydration facial", iconName: "drop.fill"),
        SalonService(name: "Anti-Aging Facial", category: "Facial", duration: 75, price: 220, stylistName: "Emma Dubois", description: "Rejuvenating treatment with collagen boost", iconName: "sparkles"),
        SalonService(name: "LED Light Therapy", category: "Facial", duration: 30, price: 95, stylistName: "Emma Dubois", description: "Skin renewal with therapeutic light", iconName: "sun.max.fill"),
        SalonService(name: "Hot Stone Massage", category: "Massage", duration: 90, price: 175, stylistName: "Aria Kim", description: "Deep relaxation with heated basalt stones", iconName: "flame.fill"),
        SalonService(name: "Swedish Massage", category: "Massage", duration: 60, price: 130, stylistName: "Aria Kim", description: "Classic full-body relaxation massage", iconName: "leaf.fill"),
        SalonService(name: "Aromatherapy", category: "Massage", duration: 75, price: 155, stylistName: "Aria Kim", description: "Essential oil massage for mind and body", iconName: "humidity.fill"),
    ]

    static let stylists: [Stylist] = [
        Stylist(name: "Sophia Laurent", specialty: "Hair Colorist", rating: 4.9, reviewCount: 234, initials: "SL"),
        Stylist(name: "Isabella Rose", specialty: "Nail Artist", rating: 4.8, reviewCount: 189, initials: "IR"),
        Stylist(name: "Emma Dubois", specialty: "Skincare Expert", rating: 4.9, reviewCount: 312, initials: "ED"),
        Stylist(name: "Aria Kim", specialty: "Massage Therapist", rating: 5.0, reviewCount: 276, initials: "AK"),
    ]

    static let timeSlots: [TimeSlot] = [
        TimeSlot(time: "9:00 AM", available: true),
        TimeSlot(time: "9:30 AM", available: false),
        TimeSlot(time: "10:00 AM", available: true),
        TimeSlot(time: "10:30 AM", available: true),
        TimeSlot(time: "11:00 AM", available: false),
        TimeSlot(time: "11:30 AM", available: true),
        TimeSlot(time: "12:00 PM", available: false),
        TimeSlot(time: "12:30 PM", available: false),
        TimeSlot(time: "1:00 PM", available: true),
        TimeSlot(time: "1:30 PM", available: true),
        TimeSlot(time: "2:00 PM", available: true),
        TimeSlot(time: "2:30 PM", available: false),
        TimeSlot(time: "3:00 PM", available: true),
        TimeSlot(time: "3:30 PM", available: true),
        TimeSlot(time: "4:00 PM", available: true),
        TimeSlot(time: "4:30 PM", available: false),
    ]

    static let upcomingAppointments: [Appointment] = [
        Appointment(serviceName: "Balayage Color", stylistName: "Sophia Laurent", date: "Oct 8, 2026", time: "10:00 AM", status: .confirmed, price: 250, duration: 120),
        Appointment(serviceName: "Gel Manicure", stylistName: "Isabella Rose", date: "Oct 12, 2026", time: "2:00 PM", status: .confirmed, price: 55, duration: 45),
    ]

    static let pastAppointments: [Appointment] = [
        Appointment(serviceName: "HydraFacial", stylistName: "Emma Dubois", date: "Sep 28, 2026", time: "11:00 AM", status: .completed, price: 185, duration: 60),
        Appointment(serviceName: "Swedish Massage", stylistName: "Aria Kim", date: "Sep 20, 2026", time: "3:00 PM", status: .completed, price: 130, duration: 60),
        Appointment(serviceName: "Precision Haircut", stylistName: "Mia Chen", date: "Sep 15, 2026", time: "1:30 PM", status: .cancelled, price: 120, duration: 60),
        Appointment(serviceName: "Spa Pedicure", stylistName: "Isabella Rose", date: "Sep 5, 2026", time: "10:30 AM", status: .completed, price: 75, duration: 60),
    ]
}
