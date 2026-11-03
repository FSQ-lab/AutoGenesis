const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function copyDir(src, dest, options = {}) {
    if (!fs.existsSync(src)) {
        console.warn(`Warning: Source directory does not exist: ${src}`);
        return;
    }
    if (!fs.existsSync(dest)) {
        fs.mkdirSync(dest, { recursive: true });
    }

    for (const file of fs.readdirSync(src)) {
        const srcPath = path.join(src, file);
        const destPath = path.join(dest, file);
        const stat = fs.statSync(srcPath);
        if (stat.isDirectory()) {
            copyDir(srcPath, destPath, options);
        } else if (!(options.skipTsFiles && (file.endsWith('.ts') || file.endsWith('.tsx')))) {
            fs.copyFileSync(srcPath, destPath);
        }
    }
}

function compile() {
    console.log('Starting extension compilation...');
    try {
        execSync('tsc -p ./', { stdio: 'inherit' });

        const srcResources = path.join(__dirname, '..', 'resources');
        const destResources = path.join(__dirname, '..', 'out', 'resources');
        if (fs.existsSync(srcResources)) {
            for (const file of fs.readdirSync(srcResources)) {
                const srcPath = path.join(srcResources, file);
                const destPath = path.join(destResources, file);
                if (!fs.existsSync(destResources)) {
                    fs.mkdirSync(destResources, { recursive: true });
                }
                const stat = fs.statSync(srcPath);
                if (stat.isDirectory()) {
                    copyDir(srcPath, destPath, { skipTsFiles: true });
                } else if (!file.endsWith('.ts') && !file.endsWith('.tsx')) {
                    fs.copyFileSync(srcPath, destPath);
                }
            }
        }
        console.log('Compilation completed. Canonical MCP runtimes are installed separately.');
    } catch (error) {
        console.error('Compilation failed:', error.message);
        process.exit(1);
    }
}

if (require.main === module) {
    compile();
}

module.exports = { compile, copyDir };
