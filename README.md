# HTTrack Pro - Advanced Site Cloner GUI

A professional Python GUI wrapper for HTTrack Website Copier with advanced features, real-time progress monitoring, and enterprise-grade functionality.

![HTTrack Pro Screenshot](https://img.shields.io/badge/Python-3.9+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## 🌟 Features

### **Core Functionality**
- 🚀 **Professional GUI** with tabbed interface (Main, Advanced, Logs & Progress)
- 📊 **Real-time Progress Tracking** with percentage, file counts, and download statistics
- 🔄 **Resume Interrupted Downloads** for reliable large site mirroring
- ⚡ **Smart Presets** for common use cases with helpful tooltips
- 📋 **Batch URL Management** with import from files and clipboard support
- 🎛️ **Advanced Controls** for bandwidth, connections, depth, and filtering

### **Monitoring & Logging**
- 📈 **Live Progress Bars** with detailed download statistics
- 📝 **Color-coded Logging** with multiple levels (INFO, WARN, ERROR, DEBUG)
- 💾 **Export Logs** functionality for troubleshooting
- ⏱️ **Runtime Tracking** with elapsed time display
- 🌐 **Current URL Display** showing active downloads

### **User Experience**
- 💾 **Configuration Persistence** - saves all settings between sessions
- ✅ **Input Validation** with comprehensive URL and parameter checking
- 🧪 **HTTrack Testing** to verify installation before starting
- 🔍 **Smart Auto-detection** of HTTrack executable location
- 📁 **Quick Access** buttons to open output folders and mirrored sites

## 📋 Requirements

### System Requirements
- **Python 3.9+** (tested up to Python 3.12)
- **HTTrack Website Copier** installed on your system
- **Tkinter** (usually included with Python)

### Operating System Support
- ✅ **Windows 10/11** (with WinHTTrack)
- ✅ **macOS 10.14+** (with HTTrack via Homebrew)
- ✅ **Linux** (Ubuntu, Debian, CentOS, etc.)

## 🚀 Installation

### 1. Install Python Dependencies
```bash
pip install -r requirements.txt
```

### 2. Install HTTrack

#### Windows
1. Download and install [WinHTTrack](https://www.httrack.com/page/2/en/index.html)
2. The GUI will auto-detect the installation path

#### macOS
```bash
# Using Homebrew
brew install httrack

# Using MacPorts
sudo port install httrack
```

#### Linux (Ubuntu/Debian)
```bash
sudo apt update
sudo apt install httrack
```

#### Linux (CentOS/RHEL/Fedora)
```bash
# CentOS/RHEL
sudo yum install httrack

# Fedora
sudo dnf install httrack
```

### 3. Run the Application
```bash
python httrack_gui_enhanced.py
```

## 🎯 Quick Start

1. **Launch the application**
   ```bash
   python httrack_gui_enhanced.py
   ```

2. **Configure HTTrack path** (if not auto-detected)
   - Click "Browse..." next to "HTTrack executable"
   - Select your httrack binary

3. **Add URLs to download**
   - Type URLs directly in the text area (one per line)
   - Or use "Import from File" or "Paste from Clipboard"

4. **Choose output directory**
   - Click "Choose..." to select where files will be saved

5. **Apply presets or configure advanced options**
   - Use quick presets for common scenarios
   - Or go to "Advanced" tab for fine-tuning

6. **Start the download**
   - Click "▶ Start Download"
   - Monitor progress in real-time on the "Logs & Progress" tab

## 🎛️ Usage Guide

### **Main Tab**
- **Basic Configuration**: Set HTTrack path, URLs, and output directory
- **Quick Presets**: One-click configurations for common use cases:
  - **Complete Mirror**: Full recursive mirror ignoring robots.txt
  - **Fast Browse**: 2-level depth, same domain only  
  - **Media Rich**: Include all images, CSS, JS, and video files
  - **Documentation**: Focus on PDF and document files
  - **Offline Reading**: Optimized for offline browsing
- **Controls**: Start, pause, stop, and resume downloads
- **Options**: Auto-open folders and resume settings

### **Advanced Tab**
- **Bandwidth Control**: Set download speed limits and connection counts
- **Filtering & Limits**: Configure depth, file count, and size restrictions  
- **Custom Arguments**: Add any HTTrack command-line arguments

### **Logs & Progress Tab**
- **Real-time Progress**: Visual progress bars and download statistics
- **Activity Log**: Color-coded logging with level filtering
- **Export Functionality**: Save logs for later analysis

## 🔧 Configuration

The application automatically saves your settings to `~/.httrack_gui_config.ini` including:
- HTTrack executable path
- Default output directory  
- Preferred options and advanced settings
- Window preferences

## 📊 Preset Configurations

| Preset | Description | HTTrack Arguments |
|--------|-------------|-------------------|
| **Complete Mirror** | Full recursive mirror ignoring robots.txt | `--robots=0 -r9` |
| **Fast Browse** | Quick 2-level mirror, same domain only | `-r2 -%P` |
| **Media Rich** | Download all images, CSS, JS, videos | `+*.png +*.jpg +*.jpeg +*.gif +*.css +*.js +*.mp4` |
| **Documentation** | Focus on document files | `+*.pdf +*.doc +*.docx +*.txt` |
| **Offline Reading** | Optimized for offline browsing | `-F 'user-agent: Mozilla/5.0' --robots=0` |

## 🛠️ Advanced Features

### **Resume Functionality**
- Enable "Resume incomplete downloads" to continue interrupted downloads
- Uses HTTrack's `--update` flag to synchronize with existing mirrors

### **Bandwidth Management**
- Set maximum download speed in KB/s
- Limit concurrent connections (1-20)
- Respect server resources and your bandwidth limits

### **Progress Monitoring**
- Real-time percentage completion
- File count tracking (downloaded/total)
- Data transfer monitoring in MB
- Elapsed time display
- Current URL being processed

### **Log Management**
- Multiple log levels: ALL, INFO, WARN, ERROR
- Color-coded entries for easy scanning
- Export logs to text files
- Automatic log rotation and cleanup

## 🔍 Troubleshooting

### Common Issues

#### **HTTrack not found**
- **Windows**: Ensure WinHTTrack is installed and try these paths:
  - `C:\Program Files\WinHTTrack\httrack.exe`
  - `C:\Program Files (x86)\WinHTTrack\httrack.exe`
- **macOS/Linux**: Check if httrack is in PATH: `which httrack`

#### **Permission errors**
- Ensure output directory is writable
- On Linux/macOS, check file permissions: `chmod 755 output_directory`

#### **Download fails**
- Check URL validity using the "Validate URLs" button
- Review robots.txt restrictions (use `--robots=0` to ignore)
- Monitor logs for specific error messages

#### **Slow downloads**
- Increase connection limit (Advanced tab)
- Remove bandwidth throttling
- Check your internet connection

### **Getting Help**

1. **Test HTTrack Installation**
   - Use the "Test" button next to HTTrack executable path
   - Verify version and functionality

2. **Check Logs**
   - Switch to "Logs & Progress" tab
   - Look for ERROR or WARN messages
   - Export logs for detailed analysis

3. **Validate Configuration**
   - Use "Validate URLs" to check URL formatting
   - Verify output directory permissions
   - Test with simple single-page downloads first

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and enhancement requests.

### **Development Setup**
```bash
git clone <repository-url>
cd httrack-pro-gui
pip install -r requirements.txt
python httrack_gui_enhanced.py
```

### **Feature Requests & Bug Reports**
- Use GitHub Issues for bug reports
- Include logs and system information
- Describe expected vs actual behavior

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- **HTTrack Team** for the excellent website copying tool
- **Python Tkinter** for the GUI framework
- **Contributors** who help improve this project

## 🔗 Related Links

- [HTTrack Official Website](https://www.httrack.com/)
- [HTTrack Documentation](https://www.httrack.com/html/index.html)
- [Python Tkinter Documentation](https://docs.python.org/3/library/tkinter.html)

---

**HTTrack Pro** - Making website mirroring simple and powerful! 🚀