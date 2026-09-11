// passage.words is deliberately stripped of all punctuation - it has to
// match word-for-word against what the alignment engine hears via speech
// recognition, which never reports punctuation (see backend/tutor/
// alignment.py and contracts/passage_schema.json). That's correct and must
// not change. But the reading screen was rendering straight from `words`,
// which meant a child never saw a period, comma, or question mark anywhere
// on screen - a real readability cost for a grade 1-3 reader, who leans on
// punctuation for pacing and sentence boundaries.
//
// This derives display-only punctuation per word by aligning `words`
// against `text` (which has real punctuation) positionally, without ever
// touching the `words` array itself. If a word's plain-text form doesn't
// match what `text` has at that position (tokenization drift, e.g. a
// hyphenated word), it degrades to showing no punctuation for that one word
// rather than risk showing it in the wrong place.

export interface WordPunctuation {
  before: string;
  after: string;
}

const TOKEN_PATTERN = /^([^A-Za-z0-9]*)([A-Za-z0-9']+(?:-[A-Za-z0-9']+)*)([^A-Za-z0-9]*)$/;

export function derivePunctuation(text: string, words: string[]): WordPunctuation[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  return words.map((word, i) => {
    const token = tokens[i];
    if (!token) return { before: "", after: "" };
    const match = token.match(TOKEN_PATTERN);
    if (!match) return { before: "", after: "" };
    const [, before, core, after] = match;
    if (core.toLowerCase() !== word.toLowerCase()) return { before: "", after: "" };
    return { before, after };
  });
}
