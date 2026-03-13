#!/bin/bash

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 项目路径
PROJECT_ROOT="/Users/a1-6/Projects/novel"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# 日志文件
BACKEND_LOG="$BACKEND_DIR/backend.log"
FRONTEND_LOG="$FRONTEND_DIR/frontend.log"

# 端口定义
BACKEND_PORT=8080
FRONTEND_PORT=3000

# 检查服务是否运行
check_service() {
    local port=$1
    local name=$2
    
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $name (端口 $port) - 运行中"
        return 0
    else
        echo -e "${RED}✗${NC} $name (端口 $port) - 已停止"
        return 1
    fi
}

# 检查Docker服务
check_docker_services() {
    cd "$BACKEND_DIR"
    
    echo -e "\n${BLUE}=== Docker 服务状态 ===${NC}"
    
    local services=("zep:8000" "neo4j:7687" "graphiti:8003" "postgres:5432")
    local all_running=true
    
    for service in "${services[@]}"; do
        local name=$(echo $service | cut -d: -f1)
        local port=$(echo $service | cut -d: -f2)
        
        if docker-compose ps | grep -q "$name.*Up"; then
            echo -e "${GREEN}✓${NC} $name (端口 $port) - 运行中"
        else
            echo -e "${RED}✗${NC} $name (端口 $port) - 已停止"
            all_running=false
        fi
    done
    
    return $([ "$all_running" = true ] && echo 0 || echo 1)
}

# 显示所有服务状态
show_status() {
    echo -e "${BLUE}=== 服务状态检查 ===${NC}\n"
    
    check_service $BACKEND_PORT "后端服务"
    check_service $FRONTEND_PORT "前端服务"
    
    check_docker_services
    
    echo -e "\n${BLUE}=== 进程信息 ===${NC}"
    local backend_pids=$(lsof -t -i:$BACKEND_PORT 2>/dev/null)
    local frontend_pids=$(lsof -t -i:$FRONTEND_PORT 2>/dev/null)
    
    if [ -n "$backend_pids" ]; then
        echo -e "后端进程: $backend_pids"
    fi
    
    if [ -n "$frontend_pids" ]; then
        echo -e "前端进程: $frontend_pids"
    fi
}

# 启动后端
start_backend() {
    echo -e "${BLUE}=== 启动后端服务 ===${NC}"
    
    if check_service $BACKEND_PORT "后端服务" >/dev/null 2>&1; then
        echo -e "${YELLOW}后端服务已在运行中${NC}"
        return 0
    fi
    
    cd "$BACKEND_DIR"
    
    if [ ! -d "venv" ]; then
        echo -e "${RED}错误: 虚拟环境不存在，请先创建: python -m venv venv${NC}"
        return 1
    fi
    
    source venv/bin/activate
    
    echo "启动后端服务..."
    nohup python -m app.main > "$BACKEND_LOG" 2>&1 &
    
    # 等待服务启动
    echo "等待服务启动..."
    sleep 3
    
    if check_service $BACKEND_PORT "后端服务" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 后端服务启动成功${NC}"
        echo "日志: $BACKEND_LOG"
        return 0
    else
        echo -e "${RED}✗ 后端服务启动失败${NC}"
        echo "请检查日志: $BACKEND_LOG"
        return 1
    fi
}

# 启动前端
start_frontend() {
    echo -e "${BLUE}=== 启动前端服务 ===${NC}"
    
    if check_service $FRONTEND_PORT "前端服务" >/dev/null 2>&1; then
        echo -e "${YELLOW}前端服务已在运行中${NC}"
        return 0
    fi
    
    cd "$FRONTEND_DIR"
    
    if [ ! -d "node_modules" ]; then
        echo "首次启动，安装依赖..."
        npm install
    fi
    
    echo "启动前端服务..."
    nohup npm run dev > "$FRONTEND_LOG" 2>&1 &
    
    # 等待服务启动
    echo "等待服务启动..."
    sleep 3
    
    if check_service $FRONTEND_PORT "前端服务" >/dev/null 2>&1; then
        echo -e "${GREEN}✓ 前端服务启动成功${NC}"
        echo "日志: $FRONTEND_LOG"
        echo "访问地址: http://localhost:$FRONTEND_PORT"
        return 0
    else
        echo -e "${RED}✗ 前端服务启动失败${NC}"
        echo "请检查日志: $FRONTEND_LOG"
        return 1
    fi
}

# 启动Docker服务
start_docker() {
    echo -e "${BLUE}=== 启动 Docker 服务 ===${NC}"
    
    cd "$BACKEND_DIR"
    
    docker-compose up -d
    
    echo "等待Docker服务启动..."
    sleep 5
    
    echo -e "${GREEN}✓ Docker 服务已启动${NC}"
}

# 启动所有服务
start_all() {
    echo -e "${GREEN}=== 启动所有服务 ===${NC}"
    
    start_docker
    echo ""
    start_backend
    echo ""
    start_frontend
    echo ""
    
    echo -e "${GREEN}=== 所有服务启动完成 ===${NC}"
    echo -e "前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}"
    echo -e "后端: ${BLUE}http://localhost:$BACKEND_PORT${NC}"
}

# 停止后端
stop_backend() {
    echo -e "${BLUE}=== 停止后端服务 ===${NC}"
    
    local pids=$(lsof -t -i:$BACKEND_PORT 2>/dev/null)
    
    if [ -z "$pids" ]; then
        echo -e "${YELLOW}后端服务未运行${NC}"
        return 0
    fi
    
    echo "停止后端服务 (PID: $pids)..."
    kill $pids
    
    sleep 2
    
    if check_service $BACKEND_PORT "后端服务" >/dev/null 2>&1; then
        echo -e "${RED}✗ 后端服务停止失败，尝试强制停止${NC}"
        kill -9 $pids
        sleep 1
    fi
    
    echo -e "${GREEN}✓ 后端服务已停止${NC}"
}

# 停止前端
stop_frontend() {
    echo -e "${BLUE}=== 停止前端服务 ===${NC}"
    
    local pids=$(lsof -t -i:$FRONTEND_PORT 2>/dev/null)
    
    if [ -z "$pids" ]; then
        echo -e "${YELLOW}前端服务未运行${NC}"
        return 0
    fi
    
    echo "停止前端服务 (PID: $pids)..."
    kill $pids
    
    sleep 2
    
    if check_service $FRONTEND_PORT "前端服务" >/dev/null 2>&1; then
        echo -e "${RED}✗ 前端服务停止失败，尝试强制停止${NC}"
        kill -9 $pids
        sleep 1
    fi
    
    echo -e "${GREEN}✓ 前端服务已停止${NC}"
}

# 停止所有服务
stop_all() {
    echo -e "${GREEN}=== 停止所有服务 ===${NC}"
    
    stop_backend
    echo ""
    stop_frontend
    echo ""
    
    echo -e "${GREEN}=== 所有服务已停止 ===${NC}"
    echo -e "提示: Docker 服务仍在运行，如需停止请执行: docker-compose stop"
}

# 重启所有服务
restart_all() {
    echo -e "${GREEN}=== 重启所有服务 ===${NC}"
    
    stop_all
    echo ""
    sleep 2
    start_all
}

# 健康检查
health_check() {
    echo -e "${BLUE}=== 健康检查 ===${NC}\n"
    
    # 检查后端健康状态
    echo "检查后端服务..."
    if curl -s http://localhost:$BACKEND_PORT > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 后端服务响应正常${NC}"
    else
        echo -e "${RED}✗ 后端服务无响应${NC}"
    fi
    
    echo ""
    
    # 检查前端健康状态
    echo "检查前端服务..."
    if curl -s http://localhost:$FRONTEND_PORT > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 前端服务响应正常${NC}"
    else
        echo -e "${RED}✗ 前端服务无响应${NC}"
    fi
    
    echo ""
    
    # 检查Docker服务
    check_docker_services
}

# 查看日志
show_logs() {
    local service=$1
    
    case $service in
        backend)
            echo -e "${BLUE}=== 后端日志 ===${NC}"
            if [ -f "$BACKEND_LOG" ]; then
                tail -50 "$BACKEND_LOG"
            else
                echo -e "${YELLOW}日志文件不存在: $BACKEND_LOG${NC}"
            fi
            ;;
        frontend)
            echo -e "${BLUE}=== 前端日志 ===${NC}"
            if [ -f "$FRONTEND_LOG" ]; then
                tail -50 "$FRONTEND_LOG"
            else
                echo -e "${YELLOW}日志文件不存在: $FRONTEND_LOG${NC}"
            fi
            ;;
        *)
            echo -e "${BLUE}=== 后端日志（最近50行） ===${NC}"
            if [ -f "$BACKEND_LOG" ]; then
                tail -50 "$BACKEND_LOG"
            else
                echo -e "${YELLOW}日志文件不存在: $BACKEND_LOG${NC}"
            fi
            
            echo -e "\n${BLUE}=== 前端日志（最近50行） ===${NC}"
            if [ -f "$FRONTEND_LOG" ]; then
                tail -50 "$FRONTEND_LOG"
            else
                echo -e "${YELLOW}日志文件不存在: $FRONTEND_LOG${NC}"
            fi
            ;;
    esac
}

# 显示帮助
show_help() {
    echo -e "${BLUE}=== 服务管理脚本使用说明 ===${NC}\n"
    echo "用法: $0 [命令] [选项]\n"
    echo "命令:"
    echo "  status              查看所有服务状态"
    echo "  start               启动所有服务"
    echo "  stop                停止所有服务"
    echo "  restart             重启所有服务"
    echo "  start-backend       仅启动后端服务"
    echo "  start-frontend      仅启动前端服务"
    echo "  stop-backend        仅停止后端服务"
    echo "  stop-frontend       仅停止前端服务"
    echo "  health              健康检查"
    echo "  logs [backend|frontend]  查看日志"
    echo "  help                显示此帮助信息\n"
    echo "示例:"
    echo "  $0 status           # 查看服务状态"
    echo "  $0 start            # 启动所有服务"
    echo "  $0 logs backend     # 查看后端日志"
    echo "  $0 health           # 健康检查\n"
}

# 主函数
main() {
    case $1 in
        status)
            show_status
            ;;
        start)
            start_all
            ;;
        stop)
            stop_all
            ;;
        restart)
            restart_all
            ;;
        start-backend)
            start_backend
            ;;
        start-frontend)
            start_frontend
            ;;
        stop-backend)
            stop_backend
            ;;
        stop-frontend)
            stop_frontend
            ;;
        health)
            health_check
            ;;
        logs)
            show_logs $2
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}错误: 未知命令 '$1'${NC}\n"
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"