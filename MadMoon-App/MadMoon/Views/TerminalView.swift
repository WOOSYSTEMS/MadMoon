import SwiftUI
import WebKit

struct TerminalView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var isLoading = true

    // Cloudflare tunnel URL — update when tunnel restarts
    // Permanent — Dublin EC2, never changes
    static var tunnelURL = "http://52.50.39.82:9999"

    var body: some View {
        NavigationStack {
            ZStack {
                Color(hex: "#0A0A0F").ignoresSafeArea()
                TerminalWebView(url: Self.tunnelURL, isLoading: $isLoading)
                if isLoading {
                    ProgressView("Connecting to MacBook...")
                        .tint(.white)
                        .foregroundStyle(.white)
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    HStack(spacing: 6) {
                        Image(systemName: "terminal.fill")
                            .font(.system(size: 14))
                            .foregroundStyle(Color(hex: "#7C3AED"))
                        Text("TERMINAL")
                            .font(.system(size: 14, weight: .bold, design: .monospaced))
                            .foregroundStyle(.white)
                            .tracking(2)
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                        .foregroundStyle(Color(hex: "#7C3AED"))
                }
            }
        }
    }
}

struct TerminalWebView: UIViewRepresentable {
    let url: String
    @Binding var isLoading: Bool

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        let wv = WKWebView(frame: .zero, configuration: config)
        wv.isOpaque = false
        wv.backgroundColor = .clear
        wv.scrollView.backgroundColor = .clear
        wv.navigationDelegate = context.coordinator
        if let u = URL(string: url) {
            wv.load(URLRequest(url: u))
        }
        return wv
    }

    func updateUIView(_ wv: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    class Coordinator: NSObject, WKNavigationDelegate {
        let parent: TerminalWebView
        init(_ parent: TerminalWebView) { self.parent = parent }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
        }

        func webView(_ webView: WKWebView, didReceiveServerRedirectForProvisionalNavigation navigation: WKNavigation!) {}

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, didReceive challenge: URLAuthenticationChallenge, completionHandler: @escaping (URLSession.AuthChallengeDisposition, URLCredential?) -> Void) {
            if challenge.protectionSpace.authenticationMethod == NSURLAuthenticationMethodHTTPBasic {
                let credential = URLCredential(user: "madmoon", password: "kossinna", persistence: .forSession)
                completionHandler(.useCredential, credential)
            } else {
                completionHandler(.performDefaultHandling, nil)
            }
        }
    }
}
