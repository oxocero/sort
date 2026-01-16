#!/usr/bin/env python3
"""
File Sorter - Organizes files by type and content using local AI models.

Uses:
- CLIP (ViT-B/32) for image/video classification
- Ollama (small model) for document/text classification
- Metadata and filename analysis as hints
"""

import os
import sys
import shutil
import argparse
import json
import hashlib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict
import mimetypes
import re

# Optional imports - checked at runtime
try:
    import torch
    from PIL import Image
    import clip
    CLIP_AVAILABLE = True
except ImportError:
    CLIP_AVAILABLE = False

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

try:
    from docx import Document as DocxDocument
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    import openpyxl
    XLSX_AVAILABLE = True
except ImportError:
    XLSX_AVAILABLE = False

try:
    from mutagen import File as MutagenFile
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class Config:
    """Configuration for the file sorter."""

    # Ollama model to use (small models for limited hardware)
    ollama_model: str = "llama3.2:3b"

    # CLIP model variant
    clip_model: str = "ViT-B/32"

    # File type categories (extension -> category)
    file_types: dict = field(default_factory=lambda: {
        # Documents
        "Documents": [
            ".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".tex",
            ".pages", ".wpd", ".wps"
        ],
        # Spreadsheets (subset of documents but often useful separate)
        "Spreadsheets": [
            ".xls", ".xlsx", ".csv", ".ods", ".numbers", ".tsv"
        ],
        # Presentations
        "Presentations": [
            ".ppt", ".pptx", ".odp", ".key"
        ],
        # Pictures
        "Pictures": [
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp",
            ".svg", ".ico", ".heic", ".heif", ".raw", ".cr2", ".nef", ".arw",
            ".psd", ".ai", ".eps"
        ],
        # Videos
        "Videos": [
            ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
            ".mpeg", ".mpg", ".3gp", ".3g2", ".ogv", ".ts", ".mts"
        ],
        # Music
        "Music": [
            ".mp3", ".flac", ".wav", ".aac", ".ogg", ".wma", ".m4a", ".opus",
            ".aiff", ".alac", ".ape", ".mid", ".midi"
        ],
        # Archives
        "Archives": [
            ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso",
            ".dmg", ".pkg"
        ],
        # Ebooks
        "Ebooks": [
            ".epub", ".mobi", ".azw", ".azw3", ".fb2", ".djvu", ".cbr", ".cbz"
        ],
        # Code
        "Code": [
            ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
            ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt",
            ".scala", ".r", ".m", ".sql", ".sh", ".bash", ".ps1", ".bat",
            ".cmd", ".html", ".css", ".scss", ".sass", ".less", ".json",
            ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg"
        ],
        # Executables
        "Programs": [
            ".exe", ".msi", ".app", ".deb", ".rpm", ".apk", ".ipa"
        ],
    })

    # Thematic categories for content classification
    thematic_categories: list = field(default_factory=lambda: [
        "anime_manga",
        "architecture",
        "art_illustration",
        "cats",
        "dogs_pets",
        "flags_symbols",
        "food_cooking",
        "gaming",
        "memes_humor",
        "music_related",
        "nature_landscapes",
        "people_portraits",
        "personal_family",
        "politics_news",
        "science_technology",
        "sports",
        "travel_places",
        "vehicles",
        "work_professional",
        "other"
    ])

    # Keywords for filename-based hints (category -> keywords)
    filename_keywords: dict = field(default_factory=lambda: {
        "anime_manga": [
            "anime", "manga", "waifu", "otaku", "kawaii", "chan", "kun", "san",
            "naruto", "onepiece", "dragonball", "ghibli", "hentai", "ecchi",
            "isekai", "shonen", "seinen", "shoujo", "vtuber"
        ],
        "architecture": [
            "building", "architecture", "house", "apartment", "skyscraper",
            "interior", "exterior", "room", "kitchen", "bathroom", "bedroom",
            "floorplan", "blueprint", "design"
        ],
        "art_illustration": [
            "art", "drawing", "painting", "illustration", "sketch", "digital",
            "artwork", "artist", "canvas", "portrait", "abstract"
        ],
        "cats": [
            "cat", "cats", "kitten", "kitty", "feline", "meow", "neko"
        ],
        "dogs_pets": [
            "dog", "dogs", "puppy", "pupper", "doggo", "canine", "pet", "pets",
            "hamster", "rabbit", "bird", "fish", "turtle"
        ],
        "flags_symbols": [
            "flag", "flags", "banner", "emblem", "symbol", "coat of arms",
            "national", "country"
        ],
        "food_cooking": [
            "food", "recipe", "cooking", "meal", "dinner", "lunch", "breakfast",
            "restaurant", "dish", "cuisine", "baking"
        ],
        "gaming": [
            "game", "gaming", "xbox", "playstation", "nintendo", "steam",
            "esports", "streamer", "twitch", "gameplay", "screenshot"
        ],
        "memes_humor": [
            "meme", "memes", "funny", "lol", "lmao", "rofl", "joke", "humor",
            "comedy", "shitpost", "dank", "cursed", "blessed"
        ],
        "music_related": [
            "album", "cover", "band", "artist", "concert", "spotify",
            "playlist", "vinyl", "cd"
        ],
        "nature_landscapes": [
            "nature", "landscape", "mountain", "forest", "beach", "ocean",
            "sunset", "sunrise", "sky", "tree", "flower", "garden", "park"
        ],
        "people_portraits": [
            "portrait", "selfie", "headshot", "profile", "face"
        ],
        "personal_family": [
            "family", "wedding", "birthday", "holiday", "christmas", "vacation",
            "trip", "personal", "private", "me", "myself", "mom", "dad",
            "brother", "sister", "baby"
        ],
        "politics_news": [
            "politics", "political", "election", "vote", "government",
            "president", "congress", "senate", "democrat", "republican",
            "news", "breaking"
        ],
        "science_technology": [
            "science", "tech", "technology", "computer", "software", "hardware",
            "ai", "robot", "space", "nasa", "physics", "chemistry", "biology"
        ],
        "sports": [
            "sports", "football", "soccer", "basketball", "baseball", "tennis",
            "golf", "hockey", "olympics", "athlete", "team", "match", "game"
        ],
        "travel_places": [
            "travel", "trip", "vacation", "tourist", "city", "country",
            "airport", "hotel", "destination"
        ],
        "vehicles": [
            "car", "cars", "vehicle", "motorcycle", "bike", "truck", "bus",
            "train", "plane", "airplane", "boat", "ship", "automotive"
        ],
        "work_professional": [
            "work", "office", "meeting", "presentation", "report", "invoice",
            "contract", "resume", "cv", "business", "professional", "corporate"
        ],
    })


# =============================================================================
# File Analyzer Classes
# =============================================================================

class CLIPAnalyzer:
    """Analyzes images using CLIP model."""

    def __init__(self, config: Config):
        self.config = config
        self.model = None
        self.preprocess = None
        self.device = None
        self.text_features = None

    def _select_device(self) -> str:
        """Select the best available device (GPU preferred, CPU fallback)."""
        if not torch.cuda.is_available():
            print("  CUDA not available, using CPU")
            return "cpu"

        try:
            # Test that CUDA actually works
            test_tensor = torch.zeros(1).cuda()
            del test_tensor

            # Check available GPU memory (need at least 1GB free for CLIP)
            gpu_mem_free = torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
            gpu_mem_free_gb = gpu_mem_free / (1024**3)

            if gpu_mem_free_gb < 1.0:
                print(f"  Warning: Low GPU memory ({gpu_mem_free_gb:.1f}GB free), using CPU")
                return "cpu"

            device_name = torch.cuda.get_device_name(0)
            print(f"  Found GPU: {device_name} ({gpu_mem_free_gb:.1f}GB free)")
            return "cuda"

        except Exception as e:
            print(f"  CUDA initialization failed ({e}), falling back to CPU")
            return "cpu"

    def initialize(self):
        """Load the CLIP model."""
        if not CLIP_AVAILABLE:
            print("Warning: CLIP not available. Install with: pip install torch torchvision clip-openai pillow")
            return False

        print(f"Loading CLIP model ({self.config.clip_model})...")

        # Select best device with fallback
        self.device = self._select_device()

        try:
            self.model, self.preprocess = clip.load(self.config.clip_model, device=self.device)
        except RuntimeError as e:
            # If GPU loading fails (e.g., out of memory), fall back to CPU
            if self.device == "cuda":
                print(f"  GPU loading failed ({e}), retrying on CPU...")
                self.device = "cpu"
                torch.cuda.empty_cache()
                self.model, self.preprocess = clip.load(self.config.clip_model, device=self.device)
            else:
                raise

        # Pre-compute text features for categories
        categories = self.config.thematic_categories
        text_prompts = [self._category_to_prompt(cat) for cat in categories]
        text_tokens = clip.tokenize(text_prompts).to(self.device)

        with torch.no_grad():
            self.text_features = self.model.encode_text(text_tokens)
            self.text_features /= self.text_features.norm(dim=-1, keepdim=True)

        print(f"  CLIP ready on {self.device.upper()}")
        return True

    def _category_to_prompt(self, category: str) -> str:
        """Convert category name to a descriptive prompt for CLIP."""
        prompts = {
            "anime_manga": "anime, manga, japanese animation style artwork",
            "architecture": "architecture, buildings, interior design, rooms",
            "art_illustration": "art, illustration, painting, digital artwork",
            "cats": "a cat, cats, kittens, feline",
            "dogs_pets": "a dog, dogs, pets, animals",
            "flags_symbols": "flags, national symbols, emblems, banners",
            "food_cooking": "food, meals, cooking, recipes, dishes",
            "gaming": "video games, gaming, screenshots, game art",
            "memes_humor": "memes, funny images, internet humor, jokes",
            "music_related": "music, album covers, concerts, bands",
            "nature_landscapes": "nature, landscapes, mountains, forests, scenery",
            "people_portraits": "people, portraits, faces, humans",
            "personal_family": "family photos, personal moments, celebrations",
            "politics_news": "politics, news, government, elections",
            "science_technology": "science, technology, computers, innovation",
            "sports": "sports, athletes, games, competitions",
            "travel_places": "travel, tourism, cities, landmarks",
            "vehicles": "cars, vehicles, motorcycles, transportation",
            "work_professional": "office work, business, professional documents",
            "other": "miscellaneous, various, random",
        }
        return prompts.get(category, category.replace("_", " "))

    def analyze_image(self, image_path: Path, filename_hint: Optional[str] = None) -> tuple[str, float]:
        """
        Analyze an image and return the best matching category.

        Returns: (category, confidence)
        """
        if self.model is None:
            return ("other", 0.0)

        try:
            image = Image.open(image_path).convert("RGB")
            image_input = self.preprocess(image).unsqueeze(0).to(self.device)

            with torch.no_grad():
                image_features = self.model.encode_image(image_input)
                image_features /= image_features.norm(dim=-1, keepdim=True)

                similarity = (100.0 * image_features @ self.text_features.T).softmax(dim=-1)
                values, indices = similarity[0].topk(3)

            best_idx = indices[0].item()
            best_confidence = values[0].item()
            category = self.config.thematic_categories[best_idx]

            return (category, best_confidence)

        except Exception as e:
            print(f"  Warning: Could not analyze {image_path.name}: {e}")
            return ("other", 0.0)


class OllamaAnalyzer:
    """Analyzes text content using Ollama."""

    def __init__(self, config: Config):
        self.config = config
        self.available = False
        self.use_gpu = True  # Ollama handles GPU internally

    def initialize(self):
        """Check if Ollama is available and detect GPU support."""
        if not OLLAMA_AVAILABLE:
            print("Warning: Ollama not available. Install with: pip install ollama")
            return False

        print(f"Loading Ollama model ({self.config.ollama_model})...")

        try:
            # Check if the model exists and get its info
            model_info = ollama.show(self.config.ollama_model)
            self.available = True

            # Check if model has GPU layers
            model_details = model_info.get("details", {})
            parameter_size = model_details.get("parameter_size", "unknown")

            # Try to detect if Ollama is using GPU by checking system
            try:
                # Quick test generation to warm up and check GPU
                test_response = ollama.generate(
                    model=self.config.ollama_model,
                    prompt="Hi",
                    options={"num_predict": 1, "num_gpu": 99}  # 99 = use all available GPU layers
                )
                print(f"  Ollama model ready ({parameter_size} parameters)")
                print(f"  Note: Ollama uses GPU automatically if available")
            except Exception:
                print(f"  Ollama model ready ({parameter_size} parameters)")

            return True
        except Exception as e:
            print(f"Warning: Ollama model '{self.config.ollama_model}' not available: {e}")
            print(f"  Try: ollama pull {self.config.ollama_model}")
            return False

    def analyze_text(self, text: str, filename_hint: str = "") -> tuple[str, float]:
        """
        Analyze text content and return the best matching category.

        Returns: (category, confidence)
        """
        if not self.available or not text.strip():
            return ("other", 0.0)

        # Truncate text to avoid context limits
        max_chars = 2000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        categories_str = ", ".join(self.config.thematic_categories)

        prompt = f"""Classify the following document into ONE of these categories:
{categories_str}

Filename hint: {filename_hint}

Document content:
{text}

Respond with ONLY the category name, nothing else. If unsure, respond with "other"."""

        try:
            response = ollama.generate(
                model=self.config.ollama_model,
                prompt=prompt,
                options={
                    "temperature": 0.1,
                    "num_predict": 50,
                    "num_gpu": 99,  # Use all available GPU layers
                }
            )

            result = response["response"].strip().lower().replace(" ", "_")

            # Validate the category
            if result in self.config.thematic_categories:
                return (result, 0.8)

            # Try to find a partial match
            for cat in self.config.thematic_categories:
                if cat in result or result in cat:
                    return (cat, 0.6)

            return ("other", 0.5)

        except Exception as e:
            print(f"  Warning: Ollama analysis failed: {e}")
            return ("other", 0.0)


class FilenameAnalyzer:
    """Analyzes filenames for category hints."""

    def __init__(self, config: Config):
        self.config = config

    def analyze(self, filepath: Path) -> tuple[str, float]:
        """
        Analyze filename and path for category hints.

        Returns: (category, confidence)
        """
        # Combine filename and parent folder names for analysis
        text = filepath.stem.lower()
        for parent in filepath.parents:
            if parent.name:
                text += " " + parent.name.lower()

        # Remove common separators and make searchable
        text = re.sub(r'[_\-\.\(\)\[\]]', ' ', text)

        scores = defaultdict(int)

        for category, keywords in self.config.filename_keywords.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    # Longer keywords = more specific = higher score
                    scores[category] += len(keyword)

        if scores:
            best_category = max(scores, key=scores.get)
            # Normalize confidence based on keyword matches
            confidence = min(scores[best_category] / 20.0, 0.9)
            return (best_category, confidence)

        return ("other", 0.0)


# =============================================================================
# Content Extractors
# =============================================================================

def extract_pdf_text(filepath: Path, max_pages: int = 5) -> str:
    """Extract text from a PDF file."""
    if not PDF_AVAILABLE:
        return ""

    try:
        with open(filepath, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text_parts = []
            for i, page in enumerate(reader.pages[:max_pages]):
                text_parts.append(page.extract_text() or "")
            return "\n".join(text_parts)
    except Exception as e:
        print(f"  Warning: Could not extract PDF text from {filepath.name}: {e}")
        return ""


def extract_docx_text(filepath: Path) -> str:
    """Extract text from a Word document."""
    if not DOCX_AVAILABLE:
        return ""

    try:
        doc = DocxDocument(filepath)
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception as e:
        print(f"  Warning: Could not extract DOCX text from {filepath.name}: {e}")
        return ""


def extract_xlsx_text(filepath: Path, max_rows: int = 50) -> str:
    """Extract text from an Excel spreadsheet."""
    if not XLSX_AVAILABLE:
        return ""

    try:
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        text_parts = []
        for sheet in wb.worksheets[:3]:  # First 3 sheets
            for row in list(sheet.iter_rows(max_row=max_rows, values_only=True)):
                row_text = " ".join(str(cell) for cell in row if cell)
                if row_text.strip():
                    text_parts.append(row_text)
        return "\n".join(text_parts)
    except Exception as e:
        print(f"  Warning: Could not extract XLSX text from {filepath.name}: {e}")
        return ""


def extract_text_file(filepath: Path, max_chars: int = 5000) -> str:
    """Extract text from a plain text file."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read(max_chars)
    except Exception as e:
        print(f"  Warning: Could not read text from {filepath.name}: {e}")
        return ""


def extract_music_metadata(filepath: Path) -> dict:
    """Extract metadata from a music file."""
    if not MUTAGEN_AVAILABLE:
        return {}

    try:
        audio = MutagenFile(filepath, easy=True)
        if audio:
            return {
                "artist": audio.get("artist", [""])[0] if audio.get("artist") else "",
                "album": audio.get("album", [""])[0] if audio.get("album") else "",
                "genre": audio.get("genre", [""])[0] if audio.get("genre") else "",
                "title": audio.get("title", [""])[0] if audio.get("title") else "",
            }
    except Exception:
        pass
    return {}


def extract_video_frame(filepath: Path) -> Optional[Image.Image]:
    """Extract a frame from a video file for analysis."""
    if not CV2_AVAILABLE:
        return None

    try:
        cap = cv2.VideoCapture(str(filepath))
        # Get frame from 10% into the video
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, total_frames // 10)
        ret, frame = cap.read()
        cap.release()

        if ret:
            # Convert BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(frame_rgb)
    except Exception as e:
        print(f"  Warning: Could not extract video frame from {filepath.name}: {e}")

    return None


# =============================================================================
# Main File Sorter
# =============================================================================

class FileSorter:
    """Main class for sorting files."""

    def __init__(self, config: Config, source_dir: Path, dest_dir: Path, dry_run: bool = False):
        self.config = config
        self.source_dir = source_dir
        self.dest_dir = dest_dir
        self.dry_run = dry_run

        self.clip_analyzer = CLIPAnalyzer(config)
        self.ollama_analyzer = OllamaAnalyzer(config)
        self.filename_analyzer = FilenameAnalyzer(config)

        # Build extension lookup
        self.ext_to_type = {}
        for file_type, extensions in config.file_types.items():
            for ext in extensions:
                self.ext_to_type[ext.lower()] = file_type

        # Stats
        self.stats = defaultdict(lambda: defaultdict(int))
        self.errors = []

    def initialize(self):
        """Initialize analyzers."""
        print("Initializing analyzers...")
        self.clip_analyzer.initialize()
        self.ollama_analyzer.initialize()
        print()

    def get_file_type(self, filepath: Path) -> str:
        """Determine the file type category based on extension."""
        ext = filepath.suffix.lower()
        return self.ext_to_type.get(ext, "Other")

    def analyze_file(self, filepath: Path) -> tuple[str, str, float]:
        """
        Analyze a file and determine its type and thematic category.

        Returns: (file_type, thematic_category, confidence)
        """
        file_type = self.get_file_type(filepath)
        filename_hint = filepath.stem

        # Get filename-based hint first
        fn_category, fn_confidence = self.filename_analyzer.analyze(filepath)

        category = "other"
        confidence = 0.0

        if file_type == "Pictures":
            # Use CLIP for images
            category, confidence = self.clip_analyzer.analyze_image(filepath, filename_hint)

        elif file_type == "Videos":
            # Try to extract a frame and use CLIP
            frame = extract_video_frame(filepath)
            if frame and self.clip_analyzer.model:
                try:
                    image_input = self.clip_analyzer.preprocess(frame).unsqueeze(0).to(self.clip_analyzer.device)
                    with torch.no_grad():
                        image_features = self.clip_analyzer.model.encode_image(image_input)
                        image_features /= image_features.norm(dim=-1, keepdim=True)
                        similarity = (100.0 * image_features @ self.clip_analyzer.text_features.T).softmax(dim=-1)
                        values, indices = similarity[0].topk(1)
                    category = self.config.thematic_categories[indices[0].item()]
                    confidence = values[0].item()
                except Exception:
                    pass

            # Fall back to filename if video analysis failed
            if confidence < 0.3:
                category, confidence = fn_category, fn_confidence

        elif file_type == "Documents":
            # Extract text and use Ollama
            ext = filepath.suffix.lower()
            text = ""

            if ext == ".pdf":
                text = extract_pdf_text(filepath)
            elif ext in [".doc", ".docx"]:
                text = extract_docx_text(filepath)
            elif ext in [".txt", ".md", ".rtf"]:
                text = extract_text_file(filepath)

            if text:
                category, confidence = self.ollama_analyzer.analyze_text(text, filename_hint)
            else:
                category, confidence = fn_category, fn_confidence

        elif file_type == "Spreadsheets":
            ext = filepath.suffix.lower()
            text = ""

            if ext in [".xlsx", ".xls"]:
                text = extract_xlsx_text(filepath)
            elif ext == ".csv":
                text = extract_text_file(filepath)

            if text:
                category, confidence = self.ollama_analyzer.analyze_text(text, filename_hint)
            else:
                category, confidence = fn_category, fn_confidence

        elif file_type == "Music":
            # Use metadata + filename
            metadata = extract_music_metadata(filepath)
            combined_text = " ".join(filter(None, [
                metadata.get("artist", ""),
                metadata.get("album", ""),
                metadata.get("genre", ""),
                filename_hint
            ]))

            if combined_text and self.ollama_analyzer.available:
                category, confidence = self.ollama_analyzer.analyze_text(
                    f"Music file metadata: {combined_text}",
                    filename_hint
                )
            else:
                category, confidence = fn_category, fn_confidence

        elif file_type == "Ebooks":
            # Primarily use filename analysis for ebooks
            category, confidence = fn_category, fn_confidence

        else:
            # For other types, use filename analysis
            category, confidence = fn_category, fn_confidence

        # If AI confidence is low, boost with filename hints
        if confidence < 0.4 and fn_confidence > confidence:
            category = fn_category
            confidence = fn_confidence

        return (file_type, category, confidence)

    def get_dest_path(self, filepath: Path, file_type: str, category: str) -> Path:
        """Get the destination path for a file."""
        # Structure: dest_dir / FileType / Category / filename
        dest = self.dest_dir / file_type / category / filepath.name

        # Handle duplicates
        if dest.exists():
            stem = filepath.stem
            suffix = filepath.suffix
            counter = 1
            while dest.exists():
                dest = self.dest_dir / file_type / category / f"{stem}_{counter}{suffix}"
                counter += 1

        return dest

    def process_file(self, filepath: Path) -> bool:
        """Process a single file."""
        try:
            file_type, category, confidence = self.analyze_file(filepath)
            dest_path = self.get_dest_path(filepath, file_type, category)

            conf_str = f"{confidence:.0%}" if confidence > 0 else "N/A"
            print(f"  {filepath.name}")
            print(f"    -> {file_type}/{category} ({conf_str})")

            if not self.dry_run:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(filepath), str(dest_path))

            self.stats[file_type][category] += 1
            return True

        except Exception as e:
            self.errors.append((filepath, str(e)))
            print(f"  ERROR: {filepath.name}: {e}")
            return False

    def scan_files(self) -> list[Path]:
        """Scan source directory for files."""
        files = []
        for item in self.source_dir.rglob("*"):
            if item.is_file():
                # Skip hidden files
                if not item.name.startswith("."):
                    files.append(item)
        return files

    def run(self):
        """Run the file sorting process."""
        print(f"Scanning {self.source_dir}...")
        files = self.scan_files()
        print(f"Found {len(files)} files\n")

        if not files:
            print("No files to process.")
            return

        if self.dry_run:
            print("=== DRY RUN MODE (no files will be moved) ===\n")

        print("Processing files...")
        for i, filepath in enumerate(files, 1):
            print(f"[{i}/{len(files)}]")
            self.process_file(filepath)

        # Print summary
        print("\n" + "=" * 50)
        print("SUMMARY")
        print("=" * 50)

        total = 0
        for file_type in sorted(self.stats.keys()):
            categories = self.stats[file_type]
            type_total = sum(categories.values())
            total += type_total
            print(f"\n{file_type}: {type_total} files")
            for category in sorted(categories.keys()):
                print(f"  - {category}: {categories[category]}")

        print(f"\nTotal processed: {total}")

        if self.errors:
            print(f"\nErrors: {len(self.errors)}")
            for filepath, error in self.errors[:10]:
                print(f"  - {filepath.name}: {error}")
            if len(self.errors) > 10:
                print(f"  ... and {len(self.errors) - 10} more")


# =============================================================================
# CLI Interface
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Sort files by type and content using local AI models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python file_sorter.py /path/to/messy/folder /path/to/organized
  python file_sorter.py ./Downloads ./Sorted --dry-run
  python file_sorter.py ./files ./sorted --model phi3:mini

Required packages:
  pip install torch torchvision pillow clip-openai ollama
  pip install PyPDF2 python-docx openpyxl mutagen opencv-python

For Ollama, also run:
  ollama pull llama3.2:3b
        """
    )

    parser.add_argument("source", type=Path, help="Source directory containing files to sort")
    parser.add_argument("dest", type=Path, help="Destination directory for organized files")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Show what would be done without moving files")
    parser.add_argument("--model", "-m", default="llama3.2:3b",
                        help="Ollama model to use (default: llama3.2:3b)")
    parser.add_argument("--clip-model", default="ViT-B/32",
                        help="CLIP model variant (default: ViT-B/32)")

    args = parser.parse_args()

    # Validate paths
    if not args.source.exists():
        print(f"Error: Source directory does not exist: {args.source}")
        sys.exit(1)

    if not args.source.is_dir():
        print(f"Error: Source is not a directory: {args.source}")
        sys.exit(1)

    if args.source.resolve() == args.dest.resolve():
        print("Error: Source and destination cannot be the same directory")
        sys.exit(1)

    # Create config
    config = Config(
        ollama_model=args.model,
        clip_model=args.clip_model
    )

    # Run sorter
    sorter = FileSorter(config, args.source, args.dest, dry_run=args.dry_run)
    sorter.initialize()
    sorter.run()


if __name__ == "__main__":
    main()
