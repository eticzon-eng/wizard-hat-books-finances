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
        (400, NSColor.white, "Aug 13  CURSOR USAGE JUL  Purchase  -$17.70"),
        (300, NSColor(calibratedRed: 0.78, green: 0.88, blue: 1.0, alpha: 1), "Apr 07  CURSOR AI POWERED IDE  Purchase  -$205.44"),
        (200, NSColor.white, "May 11  CURSOR USAGE MID MAY  Purchase  -$21.74"),
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

func rowColor(rep: NSBitmapImageRep, midY: CGFloat) -> (Int, Int, Int)? {
    let width = rep.pixelsWide
    let height = rep.pixelsHigh
    guard width > 4, height > 2 else { return nil }
    let y = min(max(Int((1 - midY) * CGFloat(height - 1)), 0), height - 1)
    var samples: [(Int, Int, Int)] = []
    let step = max(width / 30, 1)
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
        let rgb = (Int(red * 255), Int(green * 255), Int(blue * 255))
        if alpha > 0.4, rgb.0 + rgb.1 + rgb.2 > 180 * 3 {
            samples.append(rgb)
        }
        x += step
    }
    guard samples.count >= 3 else { return nil }
    samples.sort { ($0.0 + $0.1 + $0.2) < ($1.0 + $1.1 + $1.2) }
    return samples[samples.count / 2]
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
    let colors = rows.map { row -> (Int, Int, Int) in
        let midY = row.map { $0.box.midY }.reduce(0, +) / CGFloat(row.count)
        return rowColor(rep: rep, midY: midY) ?? (255, 255, 255)
    }
    let background = colors.sorted { ($0.0 + $0.1 + $0.2) > ($1.0 + $1.1 + $1.2) }[colors.count / 2]
    let distances = colors.map { colorDistance($0, background) }
    let medianDistance = distances.sorted()[distances.count / 2]
    var highlighted = Array(repeating: false, count: rows.count)
    for index in rows.indices {
        let text = lineText(rows[index]).lowercased()
        let header = text.contains("date") && text.contains("amount")
        if header { continue }
        if distances[index] >= 40 && distances[index] >= medianDistance + 28 {
            highlighted[index] = true
        }
    }
    var index = 0
    while index < rows.count {
        if highlighted[index] {
            var combined = rows[index]
            var next = index + 1
            while next < rows.count && highlighted[next] {
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
