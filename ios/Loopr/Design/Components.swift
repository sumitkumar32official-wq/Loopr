import SwiftUI

struct PrimaryButton: View {
    let title: String
    var isLoading = false
    var isEnabled = true
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                if isLoading { ProgressView().tint(Theme.bg) } else { Text(title).font(.loHeadline) }
            }
            .frame(maxWidth: .infinity, minHeight: 48)
            .foregroundColor(Theme.bg)
            .background(Theme.teal.opacity(isEnabled ? 1 : 0.4))
            .clipShape(RoundedRectangle(cornerRadius: 10))
        }
        .disabled(!isEnabled || isLoading)
    }
}

struct SecondaryButton: View {
    let title: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            Text(title).font(.loHeadline).foregroundColor(.white)
                .frame(maxWidth: .infinity, minHeight: 44)
                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.border))
        }
    }
}

struct Card<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        content
            .padding(Theme.Space.l)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: Theme.radius))
            .overlay(RoundedRectangle(cornerRadius: Theme.radius).stroke(Theme.border))
    }
}

struct StatusPill: View {
    let text: String
    let color: Color
    var body: some View {
        Text(text).font(.loCaption.weight(.semibold)).foregroundColor(color)
            .padding(.horizontal, 8).padding(.vertical, 3)
            .background(color.opacity(0.15)).clipShape(Capsule())
    }
}

/// Every screen renders one of these so loading / empty / error / success are never forgotten.
enum LoadState<T> {
    case idle, loading, loaded(T), empty, failed(String)
}

struct StateView<T, Content: View>: View {
    let state: LoadState<T>
    var emptyText = "Nothing here yet"
    var retry: () -> Void
    @ViewBuilder var content: (T) -> Content

    var body: some View {
        switch state {
        case .idle, .loading: ProgressView().tint(Theme.teal).frame(maxWidth: .infinity, minHeight: 200)
        case .empty: Text(emptyText).foregroundColor(Theme.textSecondary).frame(maxWidth: .infinity, minHeight: 200)
        case .failed(let msg):
            VStack(spacing: 12) {
                Text(msg).foregroundColor(Theme.danger).multilineTextAlignment(.center)
                SecondaryButton(title: "Try again", action: retry)
            }.padding()
        case .loaded(let v): content(v)
        }
    }
}
