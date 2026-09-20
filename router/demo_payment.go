package router

import (
	"github.com/QuantumNous/new-api/controller"
	"github.com/QuantumNous/new-api/middleware"
	"github.com/gin-gonic/gin"
)

func registerDemoPaymentRoutes(userRoute *gin.RouterGroup) {
	demo := userRoute.Group("/demo-payment", controller.PaymentDemoEnabled, middleware.UserAuth(), middleware.DisableCache())
	demo.GET("/status", controller.GetDemoPaymentStatus)
	demo.POST("/orders", middleware.CriticalRateLimit(), controller.CreateDemoPaymentOrder)
	demo.POST("/orders/:order_no/resolve", middleware.CriticalRateLimit(), controller.ResolveDemoPaymentOrder)
}
