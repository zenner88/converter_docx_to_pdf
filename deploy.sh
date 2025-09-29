#!/bin/bash

# DOCX to PDF Converter - Deployment Script
# This script helps deploy the application in various environments

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        log_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    log_success "Docker and Docker Compose are available"
}

# Check if running on correct branch
check_branch() {
    current_branch=$(git branch --show-current 2>/dev/null || echo "unknown")
    if [ "$current_branch" != "feature/gotenberg-integration" ]; then
        log_warning "Current branch: $current_branch"
        log_warning "Recommended branch: feature/gotenberg-integration"
        read -p "Continue anyway? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log_info "Switching to feature/gotenberg-integration branch..."
            git checkout feature/gotenberg-integration
        fi
    fi
}

# Create necessary directories
create_directories() {
    log_info "Creating necessary directories..."
    mkdir -p document logs
    chmod 755 document logs
    log_success "Directories created"
}

# Development deployment
deploy_dev() {
    log_info "Starting development deployment..."
    
    check_docker
    check_branch
    create_directories
    
    log_info "Building and starting services..."
    docker-compose up --build -d
    
    log_info "Waiting for services to be ready..."
    sleep 10
    
    # Check Gotenberg health
    if curl -f http://localhost:3000/health &>/dev/null; then
        log_success "Gotenberg is running"
    else
        log_warning "Gotenberg might not be ready yet"
    fi
    
    # Check application health
    if curl -f http://localhost:80/health &>/dev/null; then
        log_success "Application is running"
    else
        log_warning "Application might not be ready yet"
    fi
    
    log_success "Development deployment completed!"
    log_info "Access the application at: http://localhost"
    log_info "Gotenberg service at: http://localhost:3000"
    log_info "View logs with: docker-compose logs -f"
}

# Production deployment
deploy_prod() {
    log_info "Starting production deployment..."
    
    check_docker
    check_branch
    create_directories
    
    log_info "Building and starting services with production profile..."
    docker-compose --profile production up --build -d
    
    log_info "Waiting for services to be ready..."
    sleep 15
    
    # Health checks
    if curl -f http://localhost:3000/health &>/dev/null; then
        log_success "Gotenberg is running"
    else
        log_error "Gotenberg is not responding"
        exit 1
    fi
    
    if curl -f http://localhost:80/health &>/dev/null; then
        log_success "Application is running"
    else
        log_error "Application is not responding"
        exit 1
    fi
    
    if curl -f http://localhost:8080/health &>/dev/null; then
        log_success "Nginx proxy is running"
    else
        log_warning "Nginx proxy might not be ready"
    fi
    
    log_success "Production deployment completed!"
    log_info "Access the application at: http://localhost:8080 (via Nginx)"
    log_info "Direct application access: http://localhost"
    log_info "Gotenberg service: http://localhost:3000"
}

# Stop services
stop_services() {
    log_info "Stopping services..."
    docker-compose --profile production down
    log_success "Services stopped"
}

# Show logs
show_logs() {
    log_info "Showing application logs..."
    docker-compose logs -f converter
}

# Show status
show_status() {
    log_info "Service Status:"
    docker-compose ps
    
    echo
    log_info "Health Checks:"
    
    # Gotenberg
    if curl -f http://localhost:3000/health &>/dev/null; then
        log_success "Gotenberg: OK"
    else
        log_error "Gotenberg: FAIL"
    fi
    
    # Application
    if curl -f http://localhost:80/health &>/dev/null; then
        log_success "Application: OK"
        # Show queue status
        echo
        log_info "Queue Status:"
        curl -s http://localhost:80/queue/status | python3 -m json.tool 2>/dev/null || echo "Could not parse queue status"
    else
        log_error "Application: FAIL"
    fi
    
    # Nginx (if running)
    if curl -f http://localhost:8080/health &>/dev/null; then
        log_success "Nginx Proxy: OK"
    else
        log_warning "Nginx Proxy: Not running or not accessible"
    fi
}

# Update deployment
update_deployment() {
    log_info "Updating deployment..."
    
    log_info "Pulling latest changes..."
    git pull origin feature/gotenberg-integration
    
    log_info "Rebuilding and restarting services..."
    docker-compose up --build -d
    
    log_success "Deployment updated!"
}

# Show usage
usage() {
    echo "Usage: $0 {dev|prod|stop|logs|status|update}"
    echo
    echo "Commands:"
    echo "  dev     - Deploy for development (basic setup)"
    echo "  prod    - Deploy for production (with Nginx proxy)"
    echo "  stop    - Stop all services"
    echo "  logs    - Show application logs"
    echo "  status  - Show service status and health"
    echo "  update  - Update and restart deployment"
    echo
    echo "Examples:"
    echo "  $0 dev          # Start development environment"
    echo "  $0 prod         # Start production environment"
    echo "  $0 status       # Check service health"
    echo "  $0 logs         # View application logs"
}

# Main script logic
case "${1:-}" in
    dev)
        deploy_dev
        ;;
    prod)
        deploy_prod
        ;;
    stop)
        stop_services
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    update)
        update_deployment
        ;;
    *)
        usage
        exit 1
        ;;
esac
