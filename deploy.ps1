# DOCX to PDF Converter - PowerShell Deployment Script
# This script helps deploy the application on Windows using PowerShell

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("dev", "prod", "stop", "logs", "status", "update")]
    [string]$Command
)

# Colors for output
function Write-Info($message) {
    Write-Host "[INFO] $message" -ForegroundColor Blue
}

function Write-Success($message) {
    Write-Host "[SUCCESS] $message" -ForegroundColor Green
}

function Write-Warning($message) {
    Write-Host "[WARNING] $message" -ForegroundColor Yellow
}

function Write-Error($message) {
    Write-Host "[ERROR] $message" -ForegroundColor Red
}

# Check if Docker is installed
function Test-Docker {
    Write-Info "Checking Docker installation..."
    
    try {
        $dockerVersion = docker --version 2>$null
        if (-not $dockerVersion) {
            throw "Docker not found"
        }
    } catch {
        Write-Error "Docker is not installed. Please install Docker Desktop first."
        Write-Host "Download from: https://www.docker.com/products/docker-desktop"
        exit 1
    }
    
    try {
        $composeVersion = docker-compose --version 2>$null
        if (-not $composeVersion) {
            throw "Docker Compose not found"
        }
    } catch {
        Write-Error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    }
    
    Write-Success "Docker and Docker Compose are available"
}

# Check if running on correct branch
function Test-Branch {
    Write-Info "Checking current branch..."
    
    try {
        $currentBranch = git branch --show-current 2>$null
        if ($currentBranch -ne "feature/gotenberg-integration") {
            Write-Warning "Current branch: $currentBranch"
            Write-Warning "Recommended branch: feature/gotenberg-integration"
            
            $switch = Read-Host "Switch to feature/gotenberg-integration branch? (y/N)"
            if ($switch -eq "y" -or $switch -eq "Y") {
                Write-Info "Switching to feature/gotenberg-integration branch..."
                git checkout feature/gotenberg-integration
            }
        }
    } catch {
        Write-Warning "Could not determine current branch"
    }
}

# Create necessary directories
function New-Directories {
    Write-Info "Creating necessary directories..."
    
    if (-not (Test-Path "document")) {
        New-Item -ItemType Directory -Path "document" | Out-Null
    }
    if (-not (Test-Path "logs")) {
        New-Item -ItemType Directory -Path "logs" | Out-Null
    }
    
    Write-Success "Directories created"
}

# Development deployment
function Start-DevDeployment {
    Write-Info "Starting development deployment..."
    
    Test-Docker
    Test-Branch
    New-Directories
    
    Write-Info "Building and starting services..."
    $result = docker-compose up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to start services"
        exit 1
    }
    
    Write-Info "Waiting for services to be ready..."
    Start-Sleep -Seconds 10
    
    # Check Gotenberg health
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Gotenberg is running"
    } catch {
        Write-Warning "Gotenberg might not be ready yet"
    }
    
    # Check application health
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:80/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Application is running"
    } catch {
        Write-Warning "Application might not be ready yet"
    }
    
    Write-Success "Development deployment completed!"
    Write-Info "Access the application at: http://localhost"
    Write-Info "Gotenberg service at: http://localhost:3000"
    Write-Info "View logs with: docker-compose logs -f"
}

# Production deployment
function Start-ProdDeployment {
    Write-Info "Starting production deployment..."
    
    Test-Docker
    Test-Branch
    New-Directories
    
    Write-Info "Building and starting services with production profile..."
    $result = docker-compose --profile production up --build -d
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Failed to start services"
        exit 1
    }
    
    Write-Info "Waiting for services to be ready..."
    Start-Sleep -Seconds 15
    
    # Health checks
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Gotenberg is running"
    } catch {
        Write-Error "Gotenberg is not responding"
        exit 1
    }
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:80/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Application is running"
    } catch {
        Write-Error "Application is not responding"
        exit 1
    }
    
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Nginx proxy is running"
    } catch {
        Write-Warning "Nginx proxy might not be ready"
    }
    
    Write-Success "Production deployment completed!"
    Write-Info "Access the application at: http://localhost:8080 (via Nginx)"
    Write-Info "Direct application access: http://localhost"
    Write-Info "Gotenberg service: http://localhost:3000"
}

# Stop services
function Stop-Services {
    Write-Info "Stopping services..."
    docker-compose --profile production down
    Write-Success "Services stopped"
}

# Show logs
function Show-Logs {
    Write-Info "Showing application logs..."
    docker-compose logs -f converter
}

# Show status
function Show-Status {
    Write-Info "Service Status:"
    docker-compose ps
    
    Write-Host ""
    Write-Info "Health Checks:"
    
    # Gotenberg
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:3000/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Gotenberg: OK"
    } catch {
        Write-Error "Gotenberg: FAIL"
    }
    
    # Application
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:80/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Application: OK"
        
        Write-Host ""
        Write-Info "Queue Status:"
        try {
            $queueResponse = Invoke-WebRequest -Uri "http://localhost:80/queue/status" -TimeoutSec 5
            $queueResponse.Content | ConvertFrom-Json | ConvertTo-Json -Depth 10
        } catch {
            Write-Warning "Could not get queue status"
        }
    } catch {
        Write-Error "Application: FAIL"
    }
    
    # Nginx
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/health" -TimeoutSec 5 -ErrorAction Stop
        Write-Success "Nginx Proxy: OK"
    } catch {
        Write-Warning "Nginx Proxy: Not running or not accessible"
    }
}

# Update deployment
function Update-Deployment {
    Write-Info "Updating deployment..."
    
    Write-Info "Pulling latest changes..."
    git pull origin feature/gotenberg-integration
    
    Write-Info "Rebuilding and restarting services..."
    docker-compose up --build -d
    
    Write-Success "Deployment updated!"
}

# Show usage
function Show-Usage {
    Write-Host "Usage: .\deploy.ps1 -Command <command>"
    Write-Host ""
    Write-Host "Commands:"
    Write-Host "  dev     - Deploy for development (basic setup)"
    Write-Host "  prod    - Deploy for production (with Nginx proxy)"
    Write-Host "  stop    - Stop all services"
    Write-Host "  logs    - Show application logs"
    Write-Host "  status  - Show service status and health"
    Write-Host "  update  - Update and restart deployment"
    Write-Host ""
    Write-Host "Examples:"
    Write-Host "  .\deploy.ps1 -Command dev          # Start development environment"
    Write-Host "  .\deploy.ps1 -Command prod         # Start production environment"
    Write-Host "  .\deploy.ps1 -Command status       # Check service health"
    Write-Host "  .\deploy.ps1 -Command logs         # View application logs"
    Write-Host ""
    Write-Host "Requirements:"
    Write-Host "  - Docker Desktop for Windows"
    Write-Host "  - Git for Windows"
    Write-Host "  - PowerShell 5.0+"
}

# Main script logic
switch ($Command) {
    "dev" { Start-DevDeployment }
    "prod" { Start-ProdDeployment }
    "stop" { Stop-Services }
    "logs" { Show-Logs }
    "status" { Show-Status }
    "update" { Update-Deployment }
    default { Show-Usage }
}

Write-Host "Press any key to continue..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
