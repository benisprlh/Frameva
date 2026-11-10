// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "Frameva",
    platforms: [.macOS("15.0")],
    products: [.executable(name: "Frameva", targets: ["Frameva"])],
    targets: [
        .target(name: "FramevaCore"),
        .executableTarget(name: "Frameva", dependencies: ["FramevaCore"], linkerSettings: [
            .linkedFramework("SwiftUI"), .linkedFramework("AppKit"), .linkedFramework("ScreenCaptureKit"),
            .linkedFramework("AVKit"), .linkedFramework("AVFoundation"), .linkedFramework("Security")
        ]),
        .testTarget(name: "FramevaCoreTests", dependencies: ["FramevaCore"])
    ],
    swiftLanguageVersions: [.v5]
)
