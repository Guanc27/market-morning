// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "MarketMorning",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "MarketMorning", targets: ["MarketMorning"]),
    ],
    targets: [
        .executableTarget(
            name: "MarketMorning",
            path: "Sources/MarketMorning"
        ),
    ]
)
