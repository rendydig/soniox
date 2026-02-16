# YouTube Transcript to SRT Converter

This Node.js script converts YouTube transcript HTML files into standard SRT (SubRip Subtitle) format.

## Installation

Install the required dependencies:

```bash
npm install
```

## Usage

### Basic Usage

Convert the default `transcripts.html` file:

```bash
node convert-to-srt.js
```

This will create `transcripts.srt` in the same directory.

### Custom Input/Output Files

Specify custom input and output files:

```bash
node convert-to-srt.js <input-file.html> <output-file.srt>
```

Example:

```bash
node convert-to-srt.js transcripts.html output/my-subtitles.srt
```

## How It Works

The script:
1. Parses the YouTube transcript HTML structure
2. Extracts timestamps and text from each segment
3. Converts timestamps to SRT format (HH:MM:SS,mmm)
4. Calculates end times for each subtitle (using the next segment's start time)
5. Generates a properly formatted SRT file

## SRT Format

The output follows the standard SRT format:
```
1
00:00:00,000 --> 00:00:02,000
はい皆さんこんにちは

2
00:00:02,000 --> 00:00:05,000
ゆゆしのお時間です皆さん元気にしてい
```

## Requirements

- Node.js (v14 or higher recommended)
- jsdom package (for HTML parsing)
