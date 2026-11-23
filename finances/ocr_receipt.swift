import AppKit
import Foundation
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

func recognize(_ url: URL) throws {
    guard let image = NSImage(contentsOf: url) else { throw OCRError.unreadable }
    var rect = NSRect(origin: .zero, size: image.size)
    guard let cg = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        throw OCRError.unreadable
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = false
    let handler = VNImageRequestHandler(cgImage: cg, options: [:])
    try handler.perform([request])
    let lines = (request.results ?? []).sorted { $0.boundingBox.origin.y > $1.boundingBox.origin.y }
    for observation in lines {
        if let text = observation.topCandidates(1).first?.string {
            print(text)
        }
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
    } else {
        try recognize(URL(fileURLWithPath: args[1]))
    }
} catch {
    fputs("unreadable image\n", stderr)
    exit(2)
}
