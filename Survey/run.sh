

#!/bin/bash

# Survey Application Runner Script
# This script helps run the backend API and/or frontend UI

set -e  # Exit on error

# Color codes for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Function to check prerequisites
check_prerequisites() {
    print_info "Checking prerequisites..."

    # Check .NET
    if ! command -v dotnet &> /dev/null; then
        print_error ".NET SDK not found. Please install .NET 8 SDK."
        exit 1
    fi
    print_success ".NET SDK: $(dotnet --version)"

    # Check Node.js (only if running frontend)
    if [[ "$1" == "frontend" || "$1" == "all" ]]; then
        if ! command -v node &> /dev/null; then
            print_error "Node.js not found. Please install Node.js 20+ LTS."
            exit 1
        fi
        print_success "Node.js: $(node --version)"

        if ! command -v npm &> /dev/null; then
            print_error "npm not found. Please install Node.js with npm."
            exit 1
        fi
        print_success "npm: $(npm --version)"
    fi
}

# Function to run backend
run_backend() {
    print_info "Starting backend API..."
    cd "$SCRIPT_DIR/src/Survey.Api"

    # Check if restore is needed
    if [ ! -d "bin" ] || [ ! -d "obj" ]; then
        print_info "Running dotnet restore..."
        dotnet restore
    fi

    print_info "Building and running backend API..."
    print_warning "Backend will be available at: https://localhost:5001"
    print_warning "Swagger UI: https://localhost:5001/swagger"

    dotnet run
}

# Function to run frontend
run_frontend() {
    print_info "Starting frontend UI..."
    cd "$SCRIPT_DIR/survey-ui"

    # Check if node_modules exists
    if [ ! -d "node_modules" ]; then
        print_warning "node_modules not found. Installing dependencies..."
        npm install
    fi

    print_info "Starting Angular development server..."
    print_warning "Frontend will be available at: http://localhost:4200"

    npm start
}

# Function to run both (in background)
run_all() {
    print_info "Starting both backend and frontend..."

    # Start backend in background
    print_info "Starting backend API in background..."
    cd "$SCRIPT_DIR/src/Survey.Api"

    if [ ! -d "bin" ] || [ ! -d "obj" ]; then
        dotnet restore
    fi

    dotnet run > "$SCRIPT_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    print_success "Backend started with PID: $BACKEND_PID"

    # Wait a few seconds for backend to start
    print_info "Waiting for backend to start..."
    sleep 5

    # Start frontend in background
    print_info "Starting frontend UI in background..."
    cd "$SCRIPT_DIR/survey-ui"

    if [ ! -d "node_modules" ]; then
        npm install
    fi

    npm start > "$SCRIPT_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    print_success "Frontend started with PID: $FRONTEND_PID"

    print_success "================================"
    print_success "Application is running!"
    print_success "================================"
    print_info "Backend API: https://localhost:5001"
    print_info "Swagger UI: https://localhost:5001/swagger"
    print_info "Frontend UI: http://localhost:4200"
    print_info ""
    print_info "Backend PID: $BACKEND_PID (logs: backend.log)"
    print_info "Frontend PID: $FRONTEND_PID (logs: frontend.log)"
    print_info ""
    print_warning "To stop both services, run: kill $BACKEND_PID $FRONTEND_PID"
    print_warning "Or use: ./run.sh stop"

    # Save PIDs for stop command
    echo "$BACKEND_PID" > "$SCRIPT_DIR/.backend.pid"
    echo "$FRONTEND_PID" > "$SCRIPT_DIR/.frontend.pid"
}

# Function to stop all services
stop_all() {
    print_info "Stopping all services..."

    if [ -f "$SCRIPT_DIR/.backend.pid" ]; then
        BACKEND_PID=$(cat "$SCRIPT_DIR/.backend.pid")
        if ps -p $BACKEND_PID > /dev/null 2>&1; then
            kill $BACKEND_PID 2>/dev/null || true
            print_success "Backend stopped (PID: $BACKEND_PID)"
        fi
        rm "$SCRIPT_DIR/.backend.pid"
    fi

    if [ -f "$SCRIPT_DIR/.frontend.pid" ]; then
        FRONTEND_PID=$(cat "$SCRIPT_DIR/.frontend.pid")
        if ps -p $FRONTEND_PID > /dev/null 2>&1; then
            kill $FRONTEND_PID 2>/dev/null || true
            print_success "Frontend stopped (PID: $FRONTEND_PID)"
        fi
        rm "$SCRIPT_DIR/.frontend.pid"
    fi

    # Also try to kill any remaining dotnet/node processes on ports
    print_info "Cleaning up any remaining processes..."
    pkill -f "Survey.Api" 2>/dev/null || true
    pkill -f "ng serve" 2>/dev/null || true

    print_success "All services stopped."
}

# Function to show usage
show_usage() {
    echo ""
    echo "Survey Application Runner"
    echo ""
    echo "Usage: ./run.sh [command]"
    echo ""
    echo "Commands:"
    echo "  backend   - Run only the backend API (https://localhost:5001)"
    echo "  frontend  - Run only the frontend UI (http://localhost:4200)"
    echo "  all       - Run both backend and frontend in background"
    echo "  stop      - Stop all running services"
    echo "  help      - Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./run.sh backend    # Start backend API only"
    echo "  ./run.sh frontend   # Start frontend UI only"
    echo "  ./run.sh all        # Start both services"
    echo "  ./run.sh stop       # Stop all services"
    echo ""
}

# Main script logic
case "${1:-help}" in
    backend)
        check_prerequisites "backend"
        run_backend
        ;;
    frontend)
        check_prerequisites "frontend"
        run_frontend
        ;;
    all)
        check_prerequisites "all"
        run_all
        ;;
    stop)
        stop_all
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        print_error "Unknown command: $1"
        show_usage
        exit 1
        ;;
esac
