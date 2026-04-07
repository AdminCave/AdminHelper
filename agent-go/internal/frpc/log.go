package frpc

import "fmt"

const logTag = "srm-frpc-sync"

func logMsg(format string, args ...any) {
	fmt.Printf("[%s] %s\n", logTag, fmt.Sprintf(format, args...))
}
