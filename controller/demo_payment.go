package controller

import (
	"errors"
	"io"
	"net/http"

	"github.com/QuantumNous/new-api/common"
	"github.com/QuantumNous/new-api/model"
	"github.com/gin-gonic/gin"
	"gorm.io/gorm"
)

// PaymentDemoEnabled keeps the simulation opt-in and independent of live
// payment provider settings, credentials and compliance confirmation.
func PaymentDemoEnabled(c *gin.Context) {
	if !common.GetEnvOrDefaultBool("PAYMENT_DEMO_ENABLED", false) {
		c.AbortWithStatusJSON(http.StatusNotFound, gin.H{"success": false, "message": "Payment demo is disabled"})
		return
	}
	c.Next()
}

func GetDemoPaymentStatus(c *gin.Context) {
	userID := c.GetInt("id")
	orders, err := model.GetDemoPaymentOrders(userID, common.GetTimestamp())
	if err != nil {
		demoPaymentError(c, err)
		return
	}
	balance, err := model.GetDemoPaymentBalance(userID)
	if err != nil {
		demoPaymentError(c, err)
		return
	}
	common.ApiSuccess(c, gin.H{"enabled": true, "balance_cents": balance, "orders": orders})
}

func CreateDemoPaymentOrder(c *gin.Context) {
	var request struct {
		AmountCents   int64  `json:"amount_cents"`
		PaymentMethod string `json:"payment_method"`
	}
	if !decodeDemoPaymentRequest(c, &request) {
		return
	}
	order, err := model.CreateDemoPaymentOrder(c.GetInt("id"), request.AmountCents, request.PaymentMethod, common.GetTimestamp())
	if err != nil {
		demoPaymentError(c, err)
		return
	}
	common.ApiSuccess(c, order)
}

func ResolveDemoPaymentOrder(c *gin.Context) {
	var request struct {
		Outcome string `json:"outcome"`
	}
	if !decodeDemoPaymentRequest(c, &request) {
		return
	}
	userID := c.GetInt("id")
	order, err := model.ResolveDemoPaymentOrder(userID, c.Param("order_no"), request.Outcome, common.GetTimestamp())
	if err != nil {
		demoPaymentError(c, err)
		return
	}
	balance, err := model.GetDemoPaymentBalance(userID)
	if err != nil {
		demoPaymentError(c, err)
		return
	}
	common.ApiSuccess(c, gin.H{"order": order, "balance_cents": balance})
}

func decodeDemoPaymentRequest(c *gin.Context, request interface{}) bool {
	body, err := io.ReadAll(http.MaxBytesReader(c.Writer, c.Request.Body, 1024))
	if err != nil || common.Unmarshal(body, request) != nil {
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "message": "Invalid demo payment request"})
		return false
	}
	return true
}

func demoPaymentError(c *gin.Context, err error) {
	switch {
	case errors.Is(err, model.ErrDemoPaymentAmount), errors.Is(err, model.ErrDemoPaymentMethod), errors.Is(err, model.ErrDemoPaymentOutcome):
		c.JSON(http.StatusBadRequest, gin.H{"success": false, "message": err.Error()})
	case errors.Is(err, gorm.ErrRecordNotFound):
		c.JSON(http.StatusNotFound, gin.H{"success": false, "message": "Demo order not found"})
	default:
		common.SysError("demo payment: " + err.Error())
		c.JSON(http.StatusInternalServerError, gin.H{"success": false, "message": "Could not process demo payment"})
	}
}
