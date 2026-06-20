package main

import "github.com/gin-gonic/gin"

func ping(c *gin.Context) {
	c.String(200, "pong")
}

func createUser(c *gin.Context) {
	c.JSON(201, gin.H{})
}

func main() {
	r := gin.Default()
	r.GET("/ping", ping)
	r.POST("/users", createUser)
	// an anonymous handler still yields the Route (the API surface), no edge
	r.DELETE("/users/:id", func(c *gin.Context) {})
	// a dynamic (non-literal) path is counted as unresolved, not extracted
	r.GET("/dyn"+suffix, ping)
	r.Run()
}
