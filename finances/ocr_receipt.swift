import AppKit
import Foundation
import PDFKit
import Vision

enum OCRError: Error {
    case unreadable
}

func savePNG(_ image: NSImage, to url: URL) throws {
    guard let tiff = image.tiffRepresentation,
          let rep = NSBitmapImageRep(data: tiff),
          let data = rep.representation(using: .png, properties: [:]) else {
        throw OCRError.unreadable
    }
    try data.write(to: url)
}

func render(to url: URL, text: String) throws {
    let image = NSImage(size: NSSize(width: 980, height: 720))
    image.lockFocus()
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: 980, height: 720).fill()
    let paragraph = NSMutableParagraphStyle()
    paragraph.lineSpacing = 10
    let attrs: [NSAttributedString.Key: Any] = [
        .font: NSFont.monospacedSystemFont(ofSize: 34, weight: .regular),
        .foregroundColor: NSColor.black,
        .paragraphStyle: paragraph,
    ]
    text.draw(in: NSRect(x: 40, y: 40, width: 900, height: 640), withAttributes: attrs)
    image.unlockFocus()
    try savePNG(image, to: url)
}

func imageForReading(_ url: URL) -> CGImage? {
    let ext = url.pathExtension.lowercased()
    if ext == "pdf" {
        guard let document = PDFDocument(url: url), let page = document.page(at: 0) else { return nil }
        let bounds = page.bounds(for: .mediaBox)
        let scale: CGFloat = 2
        let width = Int(bounds.width * scale)
        let height = Int(bounds.height * scale)
        guard width > 0, height > 0, let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        ) else { return nil }
        context.setFillColor(NSColor.white.cgColor)
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        context.scaleBy(x: scale, y: scale)
        page.draw(with: .mediaBox, to: context)
        return context.makeImage()
    }
    guard let image = NSImage(contentsOf: url) else { return nil }
    var rect = NSRect(origin: .zero, size: image.size)
    return image.cgImage(forProposedRect: &rect, context: nil, hints: nil)
}

func renderList(to url: URL) throws {
    let width: CGFloat = 1100
    let height: CGFloat = 520
    let image = NSImage(size: NSSize(width: width, height: height))
    image.lockFocus()
    NSColor.white.setFill()
    NSRect(x: 0, y: 0, width: width, height: height).fill()
    let font = NSFont.monospacedSystemFont(ofSize: 28, weight: .regular)
    let textColor = NSColor.black
    let rows: [(CGFloat, NSColor, String)] = [
        (420, NSColor.white, "Aug 13  CURSOR USAGE JUL  Purchase  -$17.70"),
        (260, NSColor.white, "Apr 07  CURSOR USAGE MID MAY  Purchase  -$21.74"),
        (100, NSColor(calibratedRed: 0.92, green: 0.95, blue: 1.0, alpha: 1), "May 11  CURSOR AI POWERED IDE  Purchase  -$205.44"),
    ]
    for (y, color, text) in rows {
        color.setFill()
        NSRect(x: 20, y: y - 20, width: width - 40, height: 70).fill()
        text.draw(at: NSPoint(x: 40, y: y), withAttributes: [
            .font: font,
            .foregroundColor: textColor,
        ])
    }
    image.unlockFocus()
    try savePNG(image, to: url)
}

struct OCRToken {
    let text: String
    let box: CGRect
}

func colorDistance(_ left: (Int, Int, Int), _ right: (Int, Int, Int)) -> Int {
    abs(left.0 - right.0) + abs(left.1 - right.1) + abs(left.2 - right.2)
}

func isMarkedRed(_ rgb: (Int, Int, Int)) -> Bool {
    rgb.0 > 140 && rgb.0 > rgb.1 + 45 && rgb.0 > rgb.2 + 45
}

func rowColor(rep: NSBitmapImageRep, midY: CGFloat) -> (Int, Int, Int)? {
    let width = rep.pixelsWide
    let height = rep.pixelsHigh
    guard width > 4, height > 2 else { return nil }
    let center = min(max(Int((1 - midY) * CGFloat(height - 1)), 0), height - 1)
    var samples: [(Int, Int, Int)] = []
    let step = max(width / 40, 1)
    for dy in [-12, -6, 0, 6, 12] {
        let y = min(max(center + dy, 0), height - 1)
        var x = step
        while x < width - step {
            guard let color = rep.colorAt(x: x, y: y)?.usingColorSpace(.sRGB) else {
                x += step
                continue
            }
            var red: CGFloat = 0
            var green: CGFloat = 0
            var blue: CGFloat = 0
            var alpha: CGFloat = 0
            color.getRed(&red, green: &green, blue: &blue, alpha: &alpha)
            let luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue
            // Skip black text. A red row highlight is darker than white and must still count.
            if alpha > 0.4, luma > 0.08 {
                samples.append((Int(red * 255), Int(green * 255), Int(blue * 255)))
            }
            x += step
        }
    }
    guard samples.count >= 3 else { return nil }
    let reds = samples.filter(isMarkedRed)
    if reds.count >= 3, reds.count * 8 >= samples.count {
        let sorted = reds.sorted { ($0.0 + $0.1 + $0.2) < ($1.0 + $1.1 + $1.2) }
        return sorted[sorted.count / 2]
    }
    samples.sort { ($0.0 + $0.1 + $0.2) < ($1.0 + $1.1 + $1.2) }
    return samples[samples.count / 2]
}

func isStrokeRed(_ red: Int, _ green: Int, _ blue: Int) -> Bool {
    red >= 180 && green < 150 && blue < 150 && red > green + 60 && red > blue + 60
}

func redRectangle(in rep: NSBitmapImageRep) -> CGRect? {
    let width = rep.pixelsWide
    let height = rep.pixelsHigh
    guard width > 40, height > 40, let raw = rep.bitmapData else { return nil }
    let spp = rep.samplesPerPixel
    let bpr = rep.bytesPerRow
    let pixelStride = max(rep.bitsPerPixel / 8, spp)
    guard spp >= 3, pixelStride >= 3 else { return nil }
    let alphaFirst = rep.bitmapFormat.contains(.alphaFirst)
    func channels(_ x: Int, _ y: Int) -> (Int, Int, Int) {
        let pixel = raw.advanced(by: y * bpr + x * pixelStride)
        let start = alphaFirst ? 1 : 0
        return (Int(pixel[start]), Int(pixel[start + 1]), Int(pixel[start + 2]))
    }
    var minX = width
    var minY = height
    var maxX = -1
    var maxY = -1
    var count = 0
    for y in 0..<height {
        for x in stride(from: 0, to: width, by: 1) {
            let color = channels(x, y)
            if !isStrokeRed(color.0, color.1, color.2) { continue }
            count += 1
            if x < minX { minX = x }
            if y < minY { minY = y }
            if x > maxX { maxX = x }
            if y > maxY { maxY = y }
        }
    }
    guard count > 80, maxX > minX + 30, maxY > minY + 8 else { return nil }
    let boxW = maxX - minX
    let boxH = maxY - minY
    guard boxW > width / 3, boxH < height / 2 else { return nil }
    let band = max(6, boxH / 5)
    var border = 0
    var seen = 0
    for y in minY...maxY {
        for x in stride(from: minX, to: maxX + 1, by: 2) {
            let color = channels(x, y)
            if !isStrokeRed(color.0, color.1, color.2) { continue }
            seen += 1
            if x <= minX + band || x >= maxX - band || y <= minY + band || y >= maxY - band {
                border += 1
            }
        }
    }
    guard seen > 40, border * 100 / seen >= 65 else { return nil }
    return CGRect(x: minX, y: minY, width: boxW, height: boxH)
}

func tokensInside(_ tokens: [OCRToken], rect: CGRect, width: Int, height: Int) -> [OCRToken] {
    tokens.filter { token in
        let x = token.box.midX * CGFloat(width)
        let y = (1 - token.box.midY) * CGFloat(height)
        return x >= rect.minX && x <= rect.maxX && y >= rect.minY && y <= rect.maxY
    }
}

func lineText(_ tokens: [OCRToken]) -> String {
    let ordered = tokens.sorted { left, right in
        if abs(left.box.minX - right.box.minX) < 0.03 {
            return left.box.midY > right.box.midY
        }
        return left.box.minX < right.box.minX
    }
    return ordered.map { $0.text }.joined(separator: " ")
}

func groupRows(_ tokens: [OCRToken]) -> [[OCRToken]] {
    let heights = tokens.map { $0.box.height }.sorted()
    let median = heights.isEmpty ? 0.02 : heights[heights.count / 2]
    let threshold = max(median * 0.7, 0.006)
    var remaining = tokens.sorted { $0.box.midY > $1.box.midY }
    var rows: [[OCRToken]] = []
    while !remaining.isEmpty {
        let anchor = remaining[0].box.midY
        var row: [OCRToken] = []
        var rest: [OCRToken] = []
        for token in remaining {
            if abs(token.box.midY - anchor) <= threshold {
                row.append(token)
            } else {
                rest.append(token)
            }
        }
        remaining = rest
        rows.append(row)
    }
    return rows
}

func recognize(_ url: URL) throws {
    guard let cg = imageForReading(url) else { throw OCRError.unreadable }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    try handler.perform([request])
    let tokens: [OCRToken] = (request.results ?? []).compactMap { observation in
        guard let text = observation.topCandidates(1).first?.string, !text.isEmpty else { return nil }
        return OCRToken(text: text, box: observation.boundingBox)
    }
    let heights = tokens.map { $0.box.height }.sorted()
    let median = heights.isEmpty ? 0.02 : heights[heights.count / 2]
    let threshold = max(median * 0.7, 0.006)
    var remaining = tokens.sorted { $0.box.midY > $1.box.midY }
    var rows: [[OCRToken]] = []
    while !remaining.isEmpty {
        let anchor = remaining[0].box.midY
        var row: [OCRToken] = []
        var rest: [OCRToken] = []
        for token in remaining {
            if abs(token.box.midY - anchor) <= threshold {
                row.append(token)
            } else {
                rest.append(token)
            }
        }
        remaining = rest
        rows.append(row)
    }
    if rows.isEmpty { return }
    let rep = NSBitmapImageRep(cgImage: cg)
    if let rect = redRectangle(in: rep) {
        let inside = tokensInside(tokens, rect: rect, width: rep.pixelsWide, height: rep.pixelsHigh)
        if inside.count >= 2 {
            print("[[highlight]]" + lineText(inside))
            let outside = tokens.filter { token in
                let x = token.box.midX * CGFloat(rep.pixelsWide)
                let y = (1 - token.box.midY) * CGFloat(rep.pixelsHigh)
                return x < rect.minX || x > rect.maxX || y < rect.minY || y > rect.maxY
            }
            for row in groupRows(outside) {
                print(lineText(row))
            }
            return
        }
    }
    let colors = rows.map { row -> (Int, Int, Int) in
        let midY = row.map { $0.box.midY }.reduce(0, +) / CGFloat(row.count)
        return rowColor(rep: rep, midY: midY) ?? (255, 255, 255)
    }
    let background = colors.sorted { ($0.0 + $0.1 + $0.2) > ($1.0 + $1.1 + $1.2) }[colors.count / 2]
    let distances = colors.map { colorDistance($0, background) }
    func isHeader(_ index: Int) -> Bool {
        let text = lineText(rows[index]).lowercased()
        return text.contains("date") && text.contains("amount")
    }
    func hasMoney(_ index: Int) -> Bool {
        lineText(rows[index]).range(of: #"\d+\.\d{2}"#, options: .regularExpression) != nil
    }
    var best = -1
    var bestDistance = 0
    for index in rows.indices where !isHeader(index) {
        let distance = distances[index]
        // A tie keeps the lower row. That is the highlighted line when a bank list splits it.
        if distance > bestDistance || (distance == bestDistance && distance > 0) {
            bestDistance = distance
            best = index
        }
    }
    var secondDistance = 0
    if best >= 0 {
        for index in rows.indices where !isHeader(index) && abs(index - best) > 1 {
            if distances[index] > secondDistance { secondDistance = distances[index] }
        }
    }
    var chosen = Set<Int>()
    if best >= 0, bestDistance >= 18, bestDistance >= secondDistance + 8 {
        chosen.insert(best)
        for neighbor in [best - 1, best + 1] where rows.indices.contains(neighbor) && !isHeader(neighbor) {
            if distances[neighbor] + 10 < bestDistance { continue }
            if hasMoney(neighbor) && hasMoney(best) { continue }
            chosen.insert(neighbor)
        }
    }
    var index = 0
    while index < rows.count {
        if chosen.contains(index) {
            var combined = rows[index]
            var next = index + 1
            while next < rows.count && chosen.contains(next) {
                combined.append(contentsOf: rows[next])
                next += 1
            }
            print("[[highlight]]" + lineText(combined))
            index = next
            continue
        }
        print(lineText(rows[index]))
        index += 1
    }
}

let args = CommandLine.arguments
if args.count < 2 {
    fputs("usage: ocr-receipt image\n", stderr)
    exit(1)
}
do {
    if args[1] == "--render" {
        guard args.count >= 4 else {
            fputs("usage: ocr-receipt --render out.png text\n", stderr)
            exit(1)
        }
        try render(to: URL(fileURLWithPath: args[2]), text: args[3])
    } else if args[1] == "--render-list" {
        guard args.count >= 3 else {
            fputs("usage: ocr-receipt --render-list out.png\n", stderr)
            exit(1)
        }
        try renderList(to: URL(fileURLWithPath: args[2]))
    } else {
        try recognize(URL(fileURLWithPath: args[1]))
    }
} catch {
    fputs("unreadable image\n", stderr)
    exit(2)
}
