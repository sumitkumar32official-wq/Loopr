import SwiftUI

struct OnboardingView: View {
    @StateObject var vm: OnboardingViewModel
    @EnvironmentObject var session: SessionStore

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                ScrollView {
                    VStack(alignment: .leading, spacing: Theme.Space.l) {
                        switch vm.step {
                        case .society: SocietyStep(vm: vm)
                        case .flat: FlatStep(vm: vm)
                        case .vehicle: VehicleStep(vm: vm)
                        case .plan: PlanStep(vm: vm)
                        case .window: WindowStep(vm: vm)
                        case .summary: SummaryStep(vm: vm)
                        }
                        if let e = vm.error { Text(e).font(.loCaption).foregroundColor(Theme.danger) }
                    }
                    .padding(Theme.Space.l)
                }
                .scrollDismissesKeyboard(.interactively)
            }
        }
        .task { await vm.start() }
        .onChange(of: vm.finished) { _, done in if done { session.finishOnboarding() } }
    }

    private var header: some View {
        VStack(spacing: 8) {
            HStack {
                if vm.step != .society {
                    Button { vm.back() } label: { Image(systemName: "chevron.left").foregroundColor(.white) }
                        .accessibilityLabel("Back")
                }
                Text("Step \(vm.step.rawValue) of 6").font(.loCaption).foregroundColor(Theme.textSecondary)
                Spacer()
            }
            ProgressView(value: Double(vm.step.rawValue), total: 6).tint(Theme.teal)
        }
        .padding(.horizontal, Theme.Space.l).padding(.vertical, Theme.Space.m)
        .background(Theme.surface)
    }
}

// MARK: - Shared field styling
struct FieldLabel: View {
    let text: String
    var body: some View { Text(text.uppercased()).font(.loCaption.weight(.semibold)).foregroundColor(Theme.textSecondary) }
}

struct LooprField: View {
    let title: String
    @Binding var text: String
    var placeholder = ""
    var capitalization: TextInputAutocapitalization = .sentences
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            FieldLabel(text: title)
            TextField(placeholder, text: $text)
                .textInputAutocapitalization(capitalization)
                .padding(12).background(Theme.surface)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(text.isEmpty ? Theme.border : Theme.teal))
                .foregroundColor(.white)
        }
    }
}

struct ChipRow: View {
    let options: [String]
    @Binding var selection: String
    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack {
                ForEach(options, id: \.self) { o in
                    Button(o) { selection = o }
                        .font(.loBody).padding(.horizontal, 14).padding(.vertical, 7)
                        .foregroundColor(selection == o ? Theme.teal : .white)
                        .background(selection == o ? Theme.teal.opacity(0.15) : Color.clear)
                        .overlay(Capsule().stroke(selection == o ? Theme.teal : Theme.border))
                        .clipShape(Capsule())
                }
            }
        }
    }
}

// MARK: - Step 1: Society
struct SocietyStep: View {
    @ObservedObject var vm: OnboardingViewModel
    @State private var showNotListed = false

    var body: some View {
        Text("Select your society").font(.loTitle).foregroundColor(.white)
        HStack {
            Image(systemName: "magnifyingglass").foregroundColor(Theme.textSecondary)
            TextField("Search society, sector, locality...", text: $vm.query)
                .submitLabel(.search).foregroundColor(.white)
                .onSubmit { Task { await vm.searchSocieties() } }
                .onChange(of: vm.query) { _, _ in Task { try? await Task.sleep(nanoseconds: 300_000_000); await vm.searchSocieties() } }
        }
        .padding(12).background(Theme.surface).clipShape(RoundedRectangle(cornerRadius: 10))

        FieldLabel(text: vm.query.isEmpty ? "Nearest to you" : "Results")
        StateView(state: vm.societies, emptyText: "No society found", retry: { Task { await vm.searchSocieties() } }) { list in
            VStack(spacing: Theme.Space.s) {
                ForEach(list) { s in
                    HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    Text(s.name).font(.loHeadline).foregroundColor(s.live ? .white : Theme.textSecondary)
                                    if !s.live { StatusPill(text: "Coming soon", color: Theme.warning) }
                                }
                                Text("\(s.sector) · \(s.city) · \(s.units) units" + (s.distanceKm.map { " · \($0) km" } ?? ""))
                                    .font(.loCaption).foregroundColor(Theme.textSecondary)
                            }
                            Spacer()
                            if s.live { Image(systemName: "chevron.right").foregroundColor(Theme.textSecondary) }
                            else { Button("Notify me") { Task { await vm.joinWaitlist(s) } }.font(.loCaption).foregroundColor(Theme.teal) }
                        }
                        .padding(Theme.Space.m).background(Theme.card)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .contentShape(Rectangle())
                        .onTapGesture { vm.pick(s) }   // no-op for societies that are not live
                        .accessibilityAddTraits(s.live ? .isButton : [])
                }
            }
        }
        Button("My society isn't listed ->") { showNotListed = true }
            .font(.loBody).foregroundColor(Theme.teal).frame(maxWidth: .infinity)
        if let m = vm.waitlistMessage { Text(m).font(.loCaption).foregroundColor(Theme.success) }
        EmptyView().sheet(isPresented: $showNotListed) { NotListedSheet(vm: vm) }
    }
}

struct NotListedSheet: View {
    @ObservedObject var vm: OnboardingViewModel
    @Environment(\.dismiss) var dismiss
    @State private var name = ""
    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(alignment: .leading, spacing: Theme.Space.l) {
                Text("We're not there yet").font(.loTitle).foregroundColor(.white)
                Text("Join the waitlist and we'll message you when your society goes live. You can't subscribe until then.")
                    .font(.loBody).foregroundColor(Theme.textSecondary)
                LooprField(title: "Society name", text: $name, placeholder: "e.g. Sunrise Heights, Sector 62")
                PrimaryButton(title: "Join waitlist", isEnabled: name.count > 2) {
                    vm.query = name
                    Task { await vm.joinWaitlist(nil); dismiss() }
                }
                Spacer()
            }.padding(Theme.Space.l)
        }
        .presentationDetents([.medium])
    }
}

// MARK: - Step 2: Flat & parking
struct FlatStep: View {
    @ObservedObject var vm: OnboardingViewModel
    var body: some View {
        Text("Where's your car parked?").font(.loTitle).foregroundColor(.white)
        if let towers = vm.society?.towers, !towers.isEmpty {
            FieldLabel(text: "Tower")
            ChipRow(options: towers, selection: $vm.tower)
        } else {
            LooprField(title: "Tower", text: $vm.tower, placeholder: "e.g. B", capitalization: .characters)
        }
        LooprField(title: "Flat no.", text: $vm.flatNo, placeholder: "e.g. B-1204", capitalization: .characters)
        if let f = vm.floor { Text(f).font(.loCaption).foregroundColor(Theme.textSecondary) }

        FieldLabel(text: "Parking level · required")
        ChipRow(options: vm.parkingOptions, selection: $vm.parkingLevel)
        if vm.society?.hasBasement == false {
            Text("No basement here - open/surface parking only.").font(.loCaption).foregroundColor(Theme.textSecondary)
        }
        LooprField(title: "Slot number · required", text: $vm.slot, placeholder: "e.g. B2-047", capitalization: .characters)
        Text("The number painted on the floor or assigned by your society.").font(.loCaption).foregroundColor(Theme.textSecondary)
        LooprField(title: "Landmark · optional", text: $vm.landmark, placeholder: "e.g. Near lift")
        PrimaryButton(title: "Next", isLoading: vm.isLoading, isEnabled: vm.flatValid) { Task { await vm.saveFlat() } }
    }
}

// MARK: - Step 3: Vehicle
struct VehicleStep: View {
    @ObservedObject var vm: OnboardingViewModel
    var body: some View {
        Text("Add your car").font(.loTitle).foregroundColor(.white)
        LooprField(title: "Vehicle name", text: $vm.vehicleName, placeholder: "e.g. Honda City", capitalization: .words)
        FieldLabel(text: "Car size")
        HStack {
            ForEach([5, 7], id: \.self) { n in
                Button("\(n) seater") { vm.seats = n; vm.seatsTouched = true }
                    .font(.loBody).padding(.horizontal, 14).padding(.vertical, 7)
                    .foregroundColor(vm.seats == n ? Theme.teal : .white)
                    .overlay(Capsule().stroke(vm.seats == n ? Theme.teal : Theme.border))
            }
        }
        Text("Size is auto-detected from the model once saved; tap to override.").font(.loCaption).foregroundColor(Theme.textSecondary)
        LooprField(title: "Registration number · optional", text: $vm.registration, placeholder: "e.g. MH 01 AP 7788", capitalization: .characters)
        Text("Can be skipped - our team adds it later.").font(.loCaption).foregroundColor(Theme.teal)
        LooprField(title: "Nickname · optional", text: $vm.nickname, placeholder: "e.g. Office Car")
        Toggle("I also have a two-wheeler", isOn: $vm.hasBike).tint(Theme.teal).foregroundColor(.white)
            .onChange(of: vm.hasBike) { _, on in vm.addBundle = on }
        PrimaryButton(title: "Next", isLoading: vm.isLoading, isEnabled: vm.vehicleValid) { Task { await vm.saveVehicle() } }
    }
}

// MARK: - Step 4: Plan
struct PlanStep: View {
    @ObservedObject var vm: OnboardingViewModel
    var body: some View {
        Text("Your plan").font(.loTitle).foregroundColor(.white)
        Toggle("Pay yearly · save 10%", isOn: $vm.annual).tint(Theme.teal).foregroundColor(.white)
            .onChange(of: vm.annual) { _, _ in Task { await vm.planChanged() } }
        if let q = vm.quote {
            Card {
                VStack(alignment: .leading, spacing: 6) {
                    Text(q.label).font(.loHeadline).foregroundColor(.white)
                    Text("Exterior + interior wipe").font(.loCaption).foregroundColor(Theme.textSecondary)
                    Text("₹\(q.perMonth)/mo").font(.system(size: 22, weight: .bold)).foregroundColor(.white)
                    if vm.annual { Text("Billed ₹\(q.chargeNow) yearly · you save ₹\(q.annualSavings)").font(.loCaption).foregroundColor(Theme.teal) }
                }
            }.overlay(RoundedRectangle(cornerRadius: Theme.radius).stroke(Theme.teal))
            if vm.hasBike {
                Toggle("Add bike to bundle", isOn: $vm.addBundle).tint(Theme.teal).foregroundColor(.white)
                    .onChange(of: vm.addBundle) { _, _ in Task { await vm.planChanged() } }
            }
            PrimaryButton(title: "Continue — ₹\(q.perMonth)/mo", isLoading: vm.isLoading) { vm.step = .window }
        } else {
            ProgressView().tint(Theme.teal)
        }
    }
}

// MARK: - Step 5: Clean window
struct WindowStep: View {
    @ObservedObject var vm: OnboardingViewModel
    var body: some View {
        Text("When do you prefer your car cleaned?").font(.loTitle).foregroundColor(.white)
        ForEach(OnboardingViewModel.windows, id: \.key) { w in
            Button { vm.window = w.key } label: {
                HStack {
                    VStack(alignment: .leading) {
                        Text(w.title).font(.loHeadline).foregroundColor(.white)
                        Text(w.time).font(.loCaption).foregroundColor(Theme.textSecondary)
                    }
                    Spacer()
                    Image(systemName: vm.window == w.key ? "largecircle.fill.circle" : "circle")
                        .foregroundColor(vm.window == w.key ? Theme.teal : Theme.textSecondary)
                }
                .padding(Theme.Space.m).background(Theme.card)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(vm.window == w.key ? Theme.teal : Theme.border))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
        }
        Text("This is your preference - actual time depends on route.").font(.loCaption).foregroundColor(Theme.textSecondary)
        PrimaryButton(title: "Continue", isLoading: vm.isLoading) { Task { await vm.saveWindow() } }
        Button("Skip for now") { vm.window = "early_morning"; Task { await vm.saveWindow() } }
            .foregroundColor(Theme.textSecondary).frame(maxWidth: .infinity)
    }
}

// MARK: - Step 6: Summary & pay
struct SummaryStep: View {
    @ObservedObject var vm: OnboardingViewModel
    private func row(_ k: String, _ v: String) -> some View {
        HStack(alignment: .top) {
            Text(k).font(.loBody).foregroundColor(Theme.textSecondary)
            Spacer()
            Text(v).font(.loBody.weight(.semibold)).foregroundColor(.white).multilineTextAlignment(.trailing)
        }
    }
    var body: some View {
        Text("Review & confirm").font(.loTitle).foregroundColor(.white)
        Card {
            VStack(spacing: 10) {
                row("Society · Flat", "\(vm.society?.name ?? "") · \(vm.flatNo)")
                row("Parking", "\(vm.parkingLevel) \(vm.slot)" + (vm.landmark.isEmpty ? "" : " · \(vm.landmark)"))
                row("Vehicle", "\(vm.seats) seater" + (vm.registration.isEmpty ? "" : " · \(vm.registration.uppercased())"))
                row("Window", OnboardingViewModel.windows.first { $0.key == vm.window }?.title ?? "")
            }
        }
        if let q = vm.quote {
            Card {
                VStack(spacing: 10) {
                    row(q.label + (vm.addBundle ? " + bike" : ""), "₹\(q.chargeNow)")
                    row("GST", q.gst == 0 ? "₹0 · exempt" : "₹\(q.gst)")
                    Divider().background(Theme.border)
                    HStack {
                        Text("First payment today").font(.loHeadline).foregroundColor(.white)
                        Spacer()
                        Text("₹\(q.chargeNow + q.gst)").font(.loHeadline).foregroundColor(.white)
                    }
                }
            }
            Text(vm.annual ? "Billed yearly. Your first clean is tomorrow."
                           : "Then ₹\(q.chargeNow)/mo auto-deducted. Your first clean is tomorrow.")
                .font(.loCaption).foregroundColor(Theme.textSecondary)
            PrimaryButton(title: "Set up UPI Autopay", isLoading: vm.isLoading) { Task { await vm.payAndActivate() } }
            #if DEBUG
            Text("Debug build: payment is simulated through the backend webhook path.")
                .font(.loCaption).foregroundColor(Theme.warning)
            #endif
        }
    }
}
