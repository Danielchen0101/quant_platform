# English-Only Code Guidelines

## 📋 Policy
All code, comments, documentation, and file names must be in English.

## ✅ Allowed
- English variable names: `userName`, `stockPrice`, `fetchData`
- English comments: `// Get user data from API`
- English documentation: `This function retrieves stock prices`
- English file names: `dashboard.ts`, `user-service.js`
- English error messages: `User not found`
- English UI text: `Login`, `Submit`, `Cancel`

## ❌ Not Allowed
- Chinese variable names: `用户名`, `股票价格`
- Chinese comments: `// 从API获取用户数据`
- Chinese documentation: `此函数获取股票价格`
- Chinese file names: `仪表板.ts`, `用户服务.js`
- Chinese error messages: `用户未找到`
- Chinese UI text: `登录`, `提交`, `取消`

## 🔧 Verification Commands

### PowerShell (Windows)
```powershell
# Check for Chinese characters
Get-ChildItem -Recurse -Include *.js,*.ts,*.tsx,*.py,*.md,*.html | 
    Select-String "[一-龥]" | 
    Select Path, LineNumber, Line

# Run verification script
.\check-english-files.ps1
```

### Bash (Linux/Mac)
```bash
# Check for Chinese characters
grep -r "[一-龥]" --include="*.js" --include="*.ts" --include="*.tsx" --include="*.py" --include="*.md" --include="*.html" .

# Count Chinese characters
grep -o "[一-龥]" file.js | wc -l
```

## 🛠️ Fixing Chinese Text

### Manual Fix
1. Open the file in editor
2. Replace Chinese text with English equivalent
3. Save and verify

### Automated Fix (Example)
```powershell
# Replace specific Chinese text
(Get-Content file.js) -replace '用户名', 'username' | Set-Content file.js

# Replace all Chinese comments (be careful!)
(Get-Content file.js) -replace '//.*[一-龥].*', '// English comment' | Set-Content file.js
```

## 📁 File Types to Check

### Code Files
- `.js` - JavaScript files
- `.ts` - TypeScript files  
- `.tsx` - TypeScript React files
- `.py` - Python files
- `.java` - Java files
- `.cpp` - C++ files
- `.cs` - C# files

### Configuration Files
- `.json` - JSON configuration
- `.yml`, `.yaml` - YAML files
- `.xml` - XML files
- `.ini` - INI files
- `.env` - Environment files

### Documentation
- `.md` - Markdown documentation
- `.txt` - Text files
- `.html` - HTML files
- `.css` - CSS files
- `.less` - LESS files
- `.scss` - SCSS files

### Scripts
- `.bat` - Windows batch files
- `.ps1` - PowerShell scripts
- `.sh` - Shell scripts

## 🎯 Best Practices

### 1. Variable Naming
```javascript
// Good
const userName = 'John';
const stockPrice = 150.25;
const isLoggedIn = true;

// Bad
const 用户名 = 'John';  // Chinese
const 股票价格 = 150.25;  // Chinese
```

### 2. Comments
```javascript
// Good - English
// Calculate total price including tax
function calculateTotal(price, taxRate) {
  return price * (1 + taxRate);
}

// Bad - Chinese
// 计算含税总价
function 计算总价(价格, 税率) {
  return 价格 * (1 + 税率);
}
```

### 3. Error Messages
```javascript
// Good
throw new Error('User not found in database');

// Bad  
throw new Error('数据库中未找到用户');
```

### 4. Documentation
```markdown
# Good - English
## User Authentication
This module handles user login, registration, and session management.

# Bad - Chinese
## 用户认证
此模块处理用户登录、注册和会话管理。
```

## 🔍 Regular Expressions for Detection

### Chinese Characters
```regex
[一-龥]                 # Basic Chinese characters
[\u4e00-\u9fff]         # Unicode range for Chinese
[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]  # Extended Chinese
```

### Mixed Text Detection
```regex
[A-Za-z]+[一-龥]+[A-Za-z]+  # Mixed Chinese and English
```

## 🚀 Automation Scripts

### PowerShell Verification
```powershell
# check-english-files.ps1
# Use the provided script to automatically check all files
```

### Git Pre-commit Hook
```bash
#!/bin/bash
# .git/hooks/pre-commit
if grep -r "[一-龥]" --include="*.js" --include="*.ts" --include="*.py" .; then
  echo "Error: Chinese characters found in code files"
  exit 1
fi
```

## 📚 Translation Resources

### Common Translations
| Chinese | English |
|---------|---------|
| 用户 | user |
| 登录 | login |
| 注册 | register |
| 密码 | password |
| 股票 | stock |
| 价格 | price |
| 数据 | data |
| 服务 | service |
| 错误 | error |
| 成功 | success |

### Online Tools
- Google Translate: https://translate.google.com
- DeepL: https://www.deepl.com
- Microsoft Translator: https://translator.microsoft.com

## ✅ Compliance Checklist

- [ ] All variable names in English
- [ ] All function names in English  
- [ ] All class names in English
- [ ] All comments in English
- [ ] All documentation in English
- [ ] All error messages in English
- [ ] All UI text in English
- [ ] All file names in English
- [ ] All commit messages in English

## 🎉 Success Criteria

A project is considered compliant when:
1. `check-english-files.ps1` returns 0 files with Chinese
2. All team members use English in code
3. No Chinese text in production code
4. English documentation is complete and up-to-date

## 🔄 Maintenance

### Regular Checks
- Run verification script weekly
- Check new files before commit
- Review pull requests for compliance
- Update translation guide as needed

### Training
- New developers must read this guide
- Regular reminders in team meetings
- Code review focuses on language compliance

---

**Remember: English-only code improves collaboration, maintenance, and global compatibility.** 🌍