package frpc

import "fmt"

const logTag = "srm-agent-frpc"

func logMsg(format string, args ...any) {
	fmt.Printf("[%s] %s\n", logTag, fmt.Sprintf(format, args...))
}
