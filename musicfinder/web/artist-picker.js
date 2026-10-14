// Curated onboarding choices, not listening history or a recommendation model.
// Style filters only narrow these buttons; an explicit artist pick is the taste input.
export const ARTIST_STYLES = Object.freeze([
  { id: "pop", label: "Pop" },
  { id: "rock", label: "Rock" },
  { id: "indie", label: "Indie & alternative" },
  { id: "hiphop", label: "Hip-hop" },
  { id: "rnb", label: "R&B & soul" },
  { id: "electronic", label: "Electronic & dance" },
  { id: "jazz", label: "Jazz" },
  { id: "classical", label: "Classical & instrumental" },
  { id: "folk-country", label: "Folk & country" },
  { id: "latin", label: "Latin" },
  { id: "global", label: "Around the world" },
  { id: "metal-punk", label: "Metal & punk" },
].map(Object.freeze));

// Each list deliberately mixes eras. Additional tags reflect crossover artists.
const groups = {
  pop: [
    ["Taylor Swift", "folk-country"], ["ABBA"], ["Billie Eilish", "indie"],
    ["Michael Jackson", "rnb"], ["Adele", "rnb"], ["Madonna", "electronic"],
    ["Dua Lipa", "electronic"], ["Elton John", "rock"], ["Lady Gaga", "electronic"],
    ["Harry Styles", "rock"], ["Ariana Grande", "rnb"], ["Olivia Rodrigo", "rock"],
    ["Whitney Houston", "rnb"], ["Cyndi Lauper"], ["George Michael", "rnb"],
    ["Lorde", "indie"], ["Robyn", "electronic"], ["Carly Rae Jepsen"],
    ["Sabrina Carpenter"], ["Chappell Roan"], ["Troye Sivan"], ["Kate Bush", "indie"],
  ],
  rock: [
    ["The Beatles", "pop"], ["Led Zeppelin"], ["Queen", "pop"], ["Fleetwood Mac", "pop"],
    ["David Bowie", "pop", "indie"], ["Pink Floyd"], ["The Rolling Stones"],
    ["Nirvana", "indie"], ["Bruce Springsteen", "folk-country"], ["Jimi Hendrix"],
    ["The Who"], ["AC/DC", "metal-punk"], ["Pearl Jam", "indie"], ["The Doors"],
    ["R.E.M.", "indie"], ["The Police", "pop"], ["U2"], ["Foo Fighters", "indie"],
    ["Alanis Morissette", "indie"], ["Santana", "latin"], ["The Kinks"], ["Heart"],
  ],
  indie: [
    ["Radiohead", "rock", "electronic"], ["Florence + the Machine", "pop"],
    ["Arctic Monkeys", "rock"], ["Björk", "electronic", "pop"],
    ["The Cure", "rock"], ["The Smiths", "rock"], ["Phoebe Bridgers", "folk-country"],
    ["Tame Impala", "rock", "electronic"], ["Mitski", "rock"], ["The Strokes", "rock"],
    ["Bon Iver", "folk-country"], ["Beach House"], ["PJ Harvey", "rock"],
    ["Sufjan Stevens", "folk-country"], ["Big Thief", "folk-country"], ["The National", "rock"],
    ["Vampire Weekend", "rock"], ["Sonic Youth", "rock"], ["Cocteau Twins"],
    ["Portishead", "electronic"], ["Japanese Breakfast", "pop"], ["Alvvays", "pop"],
  ],
  hiphop: [
    ["Kendrick Lamar"], ["Missy Elliott", "rnb"], ["Tyler, the Creator", "rnb"],
    ["Outkast", "rnb"], ["Nas"], ["A Tribe Called Quest", "jazz"], ["Lauryn Hill", "rnb"],
    ["JAY-Z"], ["Nicki Minaj", "pop"], ["Eminem"], ["Wu-Tang Clan"], ["2Pac"],
    ["The Notorious B.I.G."], ["Drake", "rnb"], ["J. Cole"], ["Little Simz"],
    ["MF DOOM"], ["Public Enemy"], ["De La Soul", "jazz"], ["Doja Cat", "pop"],
    ["Megan Thee Stallion"], ["Run the Jewels"],
  ],
  rnb: [
    ["Beyoncé", "pop"], ["Stevie Wonder", "pop"], ["SZA", "pop"], ["Aretha Franklin"],
    ["Frank Ocean", "indie"], ["Prince", "pop", "rock"], ["Marvin Gaye"],
    ["The Weeknd", "pop"], ["Erykah Badu", "jazz"], ["D'Angelo"], ["Alicia Keys", "pop"],
    ["Otis Redding"], ["Janelle Monáe", "pop"], ["Usher", "pop"], ["Solange", "indie"],
    ["Mary J. Blige", "hiphop"], ["Sade", "jazz"], ["Al Green"], ["Nina Simone", "jazz"],
    ["Anderson .Paak", "hiphop"], ["Jill Scott"], ["Curtis Mayfield"],
  ],
  electronic: [
    ["Daft Punk", "pop"], ["Kraftwerk"], ["Aphex Twin"], ["The Chemical Brothers"],
    ["Disclosure", "pop"], ["Massive Attack", "indie"], ["Justice", "rock"], ["Four Tet"],
    ["The Prodigy", "rock"], ["Bicep"], ["LCD Soundsystem", "indie"], ["Burial"],
    ["FKA twigs", "rnb", "indie"], ["Boards of Canada"], ["Underworld"],
    ["Nia Archives", "rnb"], ["Fred again..", "pop"], ["Röyksopp"], ["Peggy Gou"],
    ["DJ Koze"], ["SOPHIE", "pop"], ["Charli xcx", "pop"],
  ],
  jazz: [
    ["Miles Davis"], ["Ella Fitzgerald"], ["John Coltrane"], ["Billie Holiday"],
    ["Herbie Hancock", "electronic"], ["Louis Armstrong"], ["Thelonious Monk"],
    ["Bill Evans"], ["Duke Ellington"], ["Chet Baker"], ["Kamasi Washington"],
    ["Esperanza Spalding", "rnb"], ["Charles Mingus"], ["Sonny Rollins"],
    ["Nubya Garcia"], ["Yussef Dayes", "rnb"], ["Diana Krall"], ["Alice Coltrane"],
    ["Art Blakey"], ["Sarah Vaughan"], ["Hiromi"], ["BADBADNOTGOOD", "hiphop"],
  ],
  classical: [
    ["Johann Sebastian Bach"], ["Frédéric Chopin"], ["Ludwig van Beethoven"],
    ["Wolfgang Amadeus Mozart"], ["Claude Debussy"], ["Yo-Yo Ma"], ["Hilary Hahn"],
    ["Ludovico Einaudi"], ["Philip Glass"], ["Max Richter"], ["Ólafur Arnalds", "electronic"],
    ["Antonio Vivaldi"], ["Pyotr Ilyich Tchaikovsky"], ["Sergei Rachmaninoff"],
    ["Gustav Mahler"], ["Arvo Pärt"], ["Víkingur Ólafsson"], ["Martha Argerich"],
    ["Florence Price"], ["Ryuichi Sakamoto", "electronic"], ["Yuja Wang"],
    ["Kronos Quartet"],
  ],
  "folk-country": [
    ["Dolly Parton", "pop"], ["Johnny Cash"], ["Joni Mitchell", "jazz"], ["Bob Dylan", "rock"],
    ["Kacey Musgraves", "pop"], ["Willie Nelson"], ["Tracy Chapman"], ["Zach Bryan"],
    ["Simon & Garfunkel", "pop"], ["Nick Drake", "indie"], ["Chris Stapleton", "rock"],
    ["Emmylou Harris"], ["Leonard Cohen"], ["Gillian Welch"], ["John Prine"],
    ["Loretta Lynn"], ["Townes Van Zandt"], ["Tyler Childers"], ["Brandi Carlile", "rock"],
    ["Alison Krauss"], ["First Aid Kit", "indie"], ["Joan Baez"],
  ],
  latin: [
    ["Bad Bunny", "hiphop"], ["Celia Cruz"], ["ROSALÍA", "pop"], ["Shakira", "pop"],
    ["Juan Luis Guerra"], ["J Balvin", "hiphop"], ["Karol G", "pop"], ["Rubén Blades"],
    ["Buena Vista Social Club"], ["Caetano Veloso", "folk-country"], ["Gilberto Gil", "global"],
    ["Jorge Ben Jor", "global"], ["Natalia Lafourcade", "folk-country"], ["Café Tacvba", "rock"],
    ["Soda Stereo", "rock"], ["Mercedes Sosa", "folk-country"], ["Luis Miguel", "pop"],
    ["Daddy Yankee", "hiphop"], ["Rauw Alejandro", "pop"], ["Bomba Estéreo", "electronic"],
    ["Julieta Venegas", "pop"], ["Seu Jorge", "global"],
  ],
  global: [
    ["BTS", "pop", "hiphop"], ["Fela Kuti", "jazz"], ["Bob Marley & The Wailers"],
    ["BLACKPINK", "pop"], ["Burna Boy", "rnb"], ["Angélique Kidjo"], ["Wizkid", "rnb"],
    ["Miriam Makeba", "jazz"], ["Rema", "pop"], ["Youssou N'Dour"], ["A. R. Rahman"],
    ["Nusrat Fateh Ali Khan"], ["Ravi Shankar", "classical"], ["Tinariwen", "rock"],
    ["Ali Farka Touré", "folk-country"], ["Mdou Moctar", "rock"], ["NewJeans", "pop"],
    ["Utada Hikaru", "pop"], ["Oumou Sangaré"], ["Lata Mangeshkar"],
    ["Anoushka Shankar", "classical"], ["Yemi Alade", "pop"],
  ],
  "metal-punk": [
    ["Metallica", "rock"], ["Black Sabbath", "rock"], ["Green Day", "rock", "pop"],
    ["Iron Maiden", "rock"], ["Paramore", "rock", "pop"], ["Rage Against the Machine", "rock"],
    ["System of a Down", "rock"], ["Slipknot"], ["Deftones", "rock", "indie"], ["Ramones", "rock"],
    ["The Clash", "rock"], ["Judas Priest", "rock"], ["My Chemical Romance", "rock"],
    ["Motörhead", "rock"], ["Turnstile", "rock"], ["Bad Brains"], ["Dead Kennedys"],
    ["Fugazi", "indie"], ["Bikini Kill", "indie"], ["Mastodon"], ["Gojira"], ["Tool", "rock"],
  ],
};

// Match the backend's artist_key rules when comparing saved and displayed names.
// JavaScript has no casefold; these two expansions cover common extra differences.
export function artistIdentity(value) {
  if (typeof value !== "string" || !value) return "";
  const folded = value.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").normalize("NFC")
    .toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ");
  const key = folded.replace(/[&+]/g, " and ").replace(/[^\p{L}\p{N}_\s]/gu, " ")
    .replace(/\s+/g, " ").trim().replace(/^the\s+/, "");
  return key || value.toLowerCase().replace(/ß/g, "ss").replace(/ς/g, "σ").trim();
}

const catalog = new Map();
for (const { id } of ARTIST_STYLES) {
  for (const [name, ...extra] of groups[id]) {
    const key = artistIdentity(name);
    const previous = catalog.get(key);
    catalog.set(key, { name, styles: [...new Set([...(previous?.styles || []), id, ...extra])] });
  }
}
export const ARTIST_CATALOG = Object.freeze([...catalog.values()].map(artist =>
  Object.freeze({ name: artist.name, styles: Object.freeze(artist.styles) })));
const byName = new Map(ARTIST_CATALOG.map(artist => [artistIdentity(artist.name), artist]));
const styleIds = new Set(ARTIST_STYLES.map(style => style.id));

// Round-robin presentation gives every style a place without a popularity score.
const balanced = [];
const seen = new Set();
for (let row = 0; row < Math.max(...Object.values(groups).map(group => group.length)); row++) {
  for (const { id } of ARTIST_STYLES) {
    const name = groups[id][row]?.[0];
    const key = artistIdentity(name);
    if (name && !seen.has(key)) {
      balanced.push(byName.get(key));
      seen.add(key);
    }
  }
}

function keys(values) {
  return new Set((Array.isArray(values) ? values : []).map(artistIdentity).filter(Boolean));
}

/**
 * Browse an offline catalog. Known explicit picks steer three of each four slots
 * by overlapping style tags; the fourth keeps an unrelated style available.
 * Filters and picks never fabricate plays, confidence or personal genre ratings.
 */
export function artistChoices(options = {}) {
  const { styles = [], selected = [], excluded = [], page = 0, limit = 24 } = options || {};
  const requested = Array.isArray(styles) ? styles : [];
  const filters = new Set(requested.filter(id => styleIds.has(id)));
  if (requested.length && !filters.size) return [];
  const selectedKeys = keys(selected);
  const excludedKeys = keys(excluded);
  const picks = [...selectedKeys].map(key => byName.get(key)).filter(Boolean);
  const candidates = balanced.filter(artist => {
    const key = artistIdentity(artist.name);
    return !selectedKeys.has(key) && !excludedKeys.has(key)
      && (!filters.size || artist.styles.some(style => filters.has(style)));
  });

  let ordered = candidates;
  if (picks.length) {
    const weights = new Map();
    for (const pick of picks) {
      for (const style of pick.styles) {
        weights.set(style, (weights.get(style) || 0) + 1 / Math.sqrt(pick.styles.length));
      }
    }
    const relevance = artist => artist.styles.reduce((score, style) => score + (weights.get(style) || 0), 0)
      / Math.sqrt(artist.styles.length);
    // Ties retain the balanced catalog order. No global popularity ranking is used.
    const related = [...candidates].sort((a, b) => relevance(b) - relevance(a));
    const exploration = candidates.filter(artist => !artist.styles.some(style => weights.has(style)));
    const used = new Set();
    ordered = [];
    let relatedIndex = 0;
    let explorationIndex = 0;
    while (ordered.length < candidates.length) {
      let next;
      if (ordered.length % 4 === 3) {
        while (explorationIndex < exploration.length && used.has(exploration[explorationIndex])) explorationIndex++;
        next = exploration[explorationIndex++];
      }
      if (!next) {
        while (relatedIndex < related.length && used.has(related[relatedIndex])) relatedIndex++;
        next = related[relatedIndex++];
      }
      if (!next) break;
      used.add(next);
      ordered.push(next);
    }
  }
  const size = Number.isFinite(Number(limit)) ? Math.min(ARTIST_CATALOG.length, Math.max(0, Math.floor(Number(limit)))) : 24;
  const index = Number.isFinite(Number(page)) ? Math.max(0, Math.floor(Number(page))) : 0;
  return ordered.slice(index * size, (index + 1) * size);
}
