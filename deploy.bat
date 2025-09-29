@echo off
REM DOCX to PDF Converter - Windows Deployment Script
REM This script helps deploy the application on Windows

setlocal EnableDelayedExpansion

REM Colors (limited in Windows CMD)
set "INFO=[INFO]"
set "SUCCESS=[SUCCESS]"
set "WARNING=[WARNING]"
set "ERROR=[ERROR]"

REM Functions equivalent
goto :main

:log_info
echo %INFO% %~1
goto :eof

:log_success
echo %SUCCESS% %~1
goto :eof

:log_warning
echo %WARNING% %~1
goto :eof

:log_error
echo %ERROR% %~1
goto :eof

:check_docker
call :log_info "Checking Docker installation..."
docker --version >nul 2>&1
if errorlevel 1 (
    call :log_error "Docker is not installed. Please install Docker Desktop first."
    echo Download from: https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

docker-compose --version >nul 2>&1
if errorlevel 1 (
    call :log_error "Docker Compose is not installed. Please install Docker Compose first."
    pause
    exit /b 1
)

call :log_success "Docker and Docker Compose are available"
goto :eof

:check_branch
call :log_info "Checking current branch..."
for /f "tokens=*" %%i in ('git branch --show-current 2^>nul') do set current_branch=%%i
if not "!current_branch!"=="feature/gotenberg-integration" (
    call :log_warning "Current branch: !current_branch!"
    call :log_warning "Recommended branch: feature/gotenberg-integration"
    set /p switch="Switch to feature/gotenberg-integration branch? (y/N): "
    if /i "!switch!"=="y" (
        call :log_info "Switching to feature/gotenberg-integration branch..."
        git checkout feature/gotenberg-integration
    )
)
goto :eof

:create_directories
call :log_info "Creating necessary directories..."
if not exist "document" mkdir document
if not exist "logs" mkdir logs
call :log_success "Directories created"
goto :eof

:deploy_dev
call :log_info "Starting development deployment..."

call :check_docker
if errorlevel 1 exit /b 1

call :check_branch
call :create_directories

call :log_info "Building and starting services..."
docker-compose up --build -d
if errorlevel 1 (
    call :log_error "Failed to start services"
    pause
    exit /b 1
)

call :log_info "Waiting for services to be ready..."
timeout /t 10 /nobreak >nul

REM Check Gotenberg health
curl -f http://localhost:3000/health >nul 2>&1
if errorlevel 1 (
    call :log_warning "Gotenberg might not be ready yet"
) else (
    call :log_success "Gotenberg is running"
)

REM Check application health
curl -f http://localhost:80/health >nul 2>&1
if errorlevel 1 (
    call :log_warning "Application might not be ready yet"
) else (
    call :log_success "Application is running"
)

call :log_success "Development deployment completed!"
call :log_info "Access the application at: http://localhost"
call :log_info "Gotenberg service at: http://localhost:3000"
call :log_info "View logs with: docker-compose logs -f"
goto :eof

:deploy_prod
call :log_info "Starting production deployment..."

call :check_docker
if errorlevel 1 exit /b 1

call :check_branch
call :create_directories

call :log_info "Building and starting services with production profile..."
docker-compose --profile production up --build -d
if errorlevel 1 (
    call :log_error "Failed to start services"
    pause
    exit /b 1
)

call :log_info "Waiting for services to be ready..."
timeout /t 15 /nobreak >nul

REM Health checks
curl -f http://localhost:3000/health >nul 2>&1
if errorlevel 1 (
    call :log_error "Gotenberg is not responding"
    pause
    exit /b 1
) else (
    call :log_success "Gotenberg is running"
)

curl -f http://localhost:80/health >nul 2>&1
if errorlevel 1 (
    call :log_error "Application is not responding"
    pause
    exit /b 1
) else (
    call :log_success "Application is running"
)

curl -f http://localhost:8080/health >nul 2>&1
if errorlevel 1 (
    call :log_warning "Nginx proxy might not be ready"
) else (
    call :log_success "Nginx proxy is running"
)

call :log_success "Production deployment completed!"
call :log_info "Access the application at: http://localhost:8080 (via Nginx)"
call :log_info "Direct application access: http://localhost"
call :log_info "Gotenberg service: http://localhost:3000"
goto :eof

:stop_services
call :log_info "Stopping services..."
docker-compose --profile production down
call :log_success "Services stopped"
goto :eof

:show_logs
call :log_info "Showing application logs..."
docker-compose logs -f converter
goto :eof

:show_status
call :log_info "Service Status:"
docker-compose ps

echo.
call :log_info "Health Checks:"

REM Gotenberg
curl -f http://localhost:3000/health >nul 2>&1
if errorlevel 1 (
    call :log_error "Gotenberg: FAIL"
) else (
    call :log_success "Gotenberg: OK"
)

REM Application
curl -f http://localhost:80/health >nul 2>&1
if errorlevel 1 (
    call :log_error "Application: FAIL"
) else (
    call :log_success "Application: OK"
    echo.
    call :log_info "Queue Status:"
    curl -s http://localhost:80/queue/status
)

REM Nginx
curl -f http://localhost:8080/health >nul 2>&1
if errorlevel 1 (
    call :log_warning "Nginx Proxy: Not running or not accessible"
) else (
    call :log_success "Nginx Proxy: OK"
)
goto :eof

:update_deployment
call :log_info "Updating deployment..."

call :log_info "Pulling latest changes..."
git pull origin feature/gotenberg-integration

call :log_info "Rebuilding and restarting services..."
docker-compose up --build -d

call :log_success "Deployment updated!"
goto :eof

:show_usage
echo Usage: %~nx0 {dev^|prod^|stop^|logs^|status^|update}
echo.
echo Commands:
echo   dev     - Deploy for development (basic setup)
echo   prod    - Deploy for production (with Nginx proxy)
echo   stop    - Stop all services
echo   logs    - Show application logs
echo   status  - Show service status and health
echo   update  - Update and restart deployment
echo.
echo Examples:
echo   %~nx0 dev          # Start development environment
echo   %~nx0 prod         # Start production environment
echo   %~nx0 status       # Check service health
echo   %~nx0 logs         # View application logs
echo.
echo Requirements:
echo   - Docker Desktop for Windows
echo   - Git for Windows
echo   - curl (usually included with Git for Windows)
goto :eof

:main
if "%~1"=="dev" (
    call :deploy_dev
) else if "%~1"=="prod" (
    call :deploy_prod
) else if "%~1"=="stop" (
    call :stop_services
) else if "%~1"=="logs" (
    call :show_logs
) else if "%~1"=="status" (
    call :show_status
) else if "%~1"=="update" (
    call :update_deployment
) else (
    call :show_usage
    pause
    exit /b 1
)

pause
endlocal
